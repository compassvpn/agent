from shared_lib.network import get_public_ip
from shared_lib.config import load_env

env_config = load_env()

instance_location_info = get_public_ip(extra=True)
instance_ip = (
    instance_location_info.get("ip", "Unknown")
    if isinstance(instance_location_info, dict)
    else "Unknown"
)

DONOR = env_config.get("DONOR", "compass")

remote_write_url = env_config.get(
    "ALLOY_REMOTE_WRITE_URL",
    env_config.get("GRAFANA_AGENT_REMOTE_WRITE_URL", ""),
)
if remote_write_url and not remote_write_url.endswith("/push"):
    remote_write_url += "/push"


def _river_escape(value: object) -> str:
    """Escape a value for safe inclusion inside a River double-quoted string.

    Without this, a stray quote/newline/brace in an interpolated value could
    terminate its string literal and inject arbitrary Alloy components.
    """
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def generate_config() -> None:
    log_level = "debug" if env_config.get("DEBUG") == "true" else "warn"
    username = env_config.get(
        "ALLOY_REMOTE_WRITE_USER",
        env_config.get("GRAFANA_AGENT_REMOTE_WRITE_USER", ""),
    )
    password = env_config.get(
        "ALLOY_REMOTE_WRITE_PASSWORD",
        env_config.get("GRAFANA_AGENT_REMOTE_WRITE_PASSWORD", ""),
    )

    # Escape every interpolated value. instance_ip in particular originates
    # from a third-party geo-IP response and is otherwise attacker-influenceable.
    log_level = _river_escape(log_level)
    username = _river_escape(username)
    password = _river_escape(password)
    url = _river_escape(remote_write_url)
    donor = _river_escape(DONOR)
    instance = _river_escape(instance_ip)

    config = f"""logging {{
  level = "{log_level}"
}}

prometheus.remote_write "default" {{
  endpoint {{
    url = "{url}"
    basic_auth {{
      username = "{username}"
      password = "{password}"
    }}
  }}
}}

prometheus.scrape "node_exporter" {{
  targets = [{{
    __address__ = "node-exporter:9100",
  }}]
  scrape_interval = "5m"
  metrics_path    = "/metrics"
  forward_to      = [prometheus.relabel.node_exporter.receiver]
}}

prometheus.relabel "node_exporter" {{
  rule {{
    source_labels = ["__name__"]
    regex         = "node_network_receive_bytes_total|node_network_transmit_bytes_total|node_cpu_seconds_total|node_memory_MemTotal_bytes|node_memory_MemFree_bytes|node_memory_Cached_bytes|node_memory_Buffers_bytes|node_filesystem_size_bytes|node_filesystem_avail_bytes"
    action        = "keep"
  }}
  rule {{
    source_labels = ["device"]
    regex         = "veth.*|io|br.*|lo|docker.*"
    action        = "drop"
  }}
  rule {{
    target_label = "donor"
    replacement  = "{donor}"
  }}
  rule {{
    target_label = "instance"
    replacement  = "{instance}"
  }}
  forward_to = [prometheus.remote_write.default.receiver]
}}

prometheus.scrape "xray" {{
  targets = [{{
    __address__ = "xray-config:5000",
  }}]
  scrape_interval = "5m"
  metrics_path    = "/metrics"
  forward_to      = [prometheus.relabel.xray.receiver]
}}

prometheus.relabel "xray" {{
  rule {{
    target_label = "donor"
    replacement  = "{donor}"
  }}
  rule {{
    target_label = "instance"
    replacement  = "{instance}"
  }}
  forward_to = [prometheus.remote_write.default.receiver]
}}

prometheus.scrape "xray_exporter" {{
  targets = [{{
    __address__ = "xray-exporter:9550",
  }}]
  scrape_interval = "5m"
  metrics_path    = "/scrape"
  forward_to      = [prometheus.relabel.xray_exporter.receiver]
}}

prometheus.relabel "xray_exporter" {{
  rule {{
    source_labels = ["__name__"]
    regex         = "go_.*|xray_memstats_.*|xray_scrape_.*|scrape_.*|promhttp_.*"
    action        = "drop"
  }}
  rule {{
    target_label = "donor"
    replacement  = "{donor}"
  }}
  rule {{
    target_label = "instance"
    replacement  = "{instance}"
  }}
  forward_to = [prometheus.remote_write.default.receiver]
}}
"""
    with open("config.alloy", "w") as f:
        f.write(config)
