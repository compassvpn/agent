import yaml

from shared_lib.network import get_public_ip
from shared_lib.config import load_env

# Load current config from env_file
env_config = load_env()

instance_location_info = get_public_ip(extra=True)
instance_ip = (
    instance_location_info.get("ip", "Unknown")
    if isinstance(instance_location_info, dict)
    else "Unknown"
)

# Use env_config as the single source of truth
DONOR = env_config.get("DONOR", "compass")

remote_write_url = env_config.get("GRAFANA_AGENT_REMOTE_WRITE_URL", "")
if remote_write_url and not remote_write_url.endswith("/push"):
    remote_write_url += "/push"


def generate_config() -> None:
    config = {
        "server": {
            "log_level": "debug" if env_config.get("DEBUG") == "true" else "warn"
        },
        "metrics": {
            "wal_directory": "/tmp/grafana-agent-wal",
            "global": {"scrape_interval": "5m"},
            "configs": [
                {
                    "name": "default",
                    "remote_write": [
                        {
                            "url": remote_write_url,
                            "basic_auth": {
                                "username": env_config.get(
                                    "GRAFANA_AGENT_REMOTE_WRITE_USER", ""
                                ),
                                "password": env_config.get(
                                    "GRAFANA_AGENT_REMOTE_WRITE_PASSWORD", ""
                                ),
                            },
                        }
                    ],
                    "scrape_configs": [
                        {
                            "job_name": "node-exporter",
                            "static_configs": [
                                {
                                    "targets": ["host.docker.internal:9100"],
                                    "labels": {"donor": DONOR, "instance": instance_ip},
                                }
                            ],
                            "metric_relabel_configs": [
                                {
                                    "source_labels": ["__name__"],
                                    "regex": "node_network_receive_bytes_total|node_network_transmit_bytes_total|node_cpu_seconds_total|node_memory_MemTotal_bytes|node_memory_MemFree_bytes|node_memory_Cached_bytes|node_memory_Buffers_bytes|node_filesystem_size_bytes|node_filesystem_avail_bytes|node_filesystem_size_bytes",
                                    "action": "keep",
                                },
                                {
                                    "source_labels": ["device"],
                                    "regex": "veth.*|io|br.*|lo|docker.*",
                                    "action": "drop",
                                },
                            ],
                            "metrics_path": "/metrics",
                        },
                        {
                            "job_name": "xray",
                            "static_configs": [
                                {
                                    "targets": [
                                        "xray-config:5000",
                                    ],
                                    "labels": {"donor": DONOR, "instance": instance_ip},
                                }
                            ],
                            "metrics_path": "/metrics",
                        },
                        {
                            "job_name": "xray-exporter",
                            "static_configs": [
                                {
                                    "targets": ["xray-exporter:9550"],
                                    "labels": {"donor": DONOR, "instance": instance_ip},
                                }
                            ],
                            "metric_relabel_configs": [
                                {
                                    "source_labels": ["__name__"],
                                    "regex": "go_.*",
                                    "action": "drop",
                                },
                                {
                                    "source_labels": ["__name__"],
                                    "regex": "xray_memstats_.*",
                                    "action": "drop",
                                },
                                {
                                    "source_labels": ["__name__"],
                                    "regex": "xray_scrape_.*",
                                    "action": "drop",
                                },
                                {
                                    "source_labels": ["__name__"],
                                    "regex": "scrape_.*",
                                    "action": "drop",
                                },
                                {
                                    "source_labels": ["__name__"],
                                    "regex": "promhttp_.*",
                                    "action": "drop",
                                },
                            ],
                            "metrics_path": "/scrape",
                        },
                    ],
                }
            ],
        },
    }
    with open("config.yaml", "w") as yaml_file:
        yaml.dump(config, yaml_file, default_flow_style=False)
