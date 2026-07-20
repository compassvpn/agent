from time import sleep

from shared_lib.network import get_public_ip
from shared_lib.config import load_env, get_identifier
from shared_lib.logger import log, is_debug

env_config = load_env()

# Resolve this node's public IP at startup. Retry a few times so a transient
# network blip doesn't permanently freeze the label, then fall back to the
# node's unique identifier - never a colliding "Unknown".
_IP_RETRIES = 5
_IP_RETRY_DELAY = 45  # seconds between attempts


def _resolve_instance_ip() -> str:
    for attempt in range(1, _IP_RETRIES + 1):
        info = get_public_ip(extra=True)
        ip = info.get("ip") if isinstance(info, dict) else None
        if ip and ip != "Unknown":
            return ip
        log.warning(
            "Public IP lookup failed; retrying",
            hypothesisId="NET",
            attempt=attempt,
            of=_IP_RETRIES,
        )
        if attempt < _IP_RETRIES:
            sleep(_IP_RETRY_DELAY)
    # Persistent failure: use the node's unique identifier so metrics stay
    # distinguishable instead of all colliding on "Unknown".
    try:
        fallback = get_identifier()
    except Exception:
        fallback = "unknown"
    log.error(
        "Public IP unresolved after retries; labeling metrics by identifier",
        hypothesisId="NET",
        instance=fallback,
    )
    return fallback


instance_ip = _resolve_instance_ip()

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
    log_level = "debug" if is_debug() else "warn"
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
    __address__ = "127.0.0.1:29100",
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
  // node_cpu_seconds_total emits one series per (core, mode), but only the
  // idle mode is graphed (CPU Usage = 100 - idle rate). Drop the 7 unused
  // modes to cut this metric ~8x; the anchored __name__ match leaves idle
  // and every other kept metric untouched.
  rule {{
    source_labels = ["__name__", "mode"]
    separator     = ";"
    regex         = "node_cpu_seconds_total;(user|nice|system|iowait|irq|softirq|steal|guest|guest_nice)"
    action        = "drop"
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
    __address__ = "127.0.0.1:25000",
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
    __address__ = "127.0.0.1:29550",
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
    with open("config.alloy", "w", encoding="utf-8") as f:
        f.write(config)
