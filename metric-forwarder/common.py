import os
import json
import yaml
from utils import get_public_ip

instance_location_info = get_public_ip(extra=True)

instance_ip = instance_location_info['ip']

DONOR = os.environ['DONOR']

remote_write_url = os.environ['GRAFANA_AGENT_REMOTE_WRITE_URL']
if not remote_write_url.endswith("/push"):
    remote_write_url += "/push"

# Convert to YAML and save to file
def generate_config():
    config = {
      "server": {
        "log_level": "info"
      },
      "metrics": {
        "wal_directory": "/tmp/grafana-agent-wal",
        "global": {
          "scrape_interval": "5m"
        },
        "configs": [
          {
            "name": "default",
            "remote_write": [
              {
                "url": remote_write_url,
                "basic_auth": {
                  "username": os.environ['GRAFANA_AGENT_REMOTE_WRITE_USER'],
                  "password": os.environ['GRAFANA_AGENT_REMOTE_WRITE_PASSWORD']
                }
              }
            ],
            "scrape_configs": [
                {
                    "job_name": "node-exporter",
                    "static_configs": [
                      {
                        "targets": [
                          "host.docker.internal:9100"
                        ],
                        "labels": {
                          "donor": DONOR,
                          "instance": instance_ip
                        }
                      }
                    ],
                    "metric_relabel_configs": [
                        {
                            "source_labels": ["__name__"],
                            "regex": "node_network_receive_bytes_total|node_network_transmit_bytes_total|node_cpu_seconds_total|node_memory_MemTotal_bytes|node_memory_MemFree_bytes|node_memory_Cached_bytes|node_memory_Buffers_bytes|node_filesystem_size_bytes|node_filesystem_avail_bytes|node_filesystem_size_bytes",
                            "action": "keep"
                        },
                        {
                            "source_labels": ["device"],
                            "regex": "veth.*|io|br.*|lo|docker.*",
                            "action": "drop"
                        }
                    ],
                    "metrics_path": "/metrics"
                },
                {
                    "job_name": "xray",
                    "static_configs": [
                        {
                            "targets": [
                                "xray-config:5000",
                            ],
                            "labels": {
                                "donor": DONOR,
                                "instance": instance_ip
                            }
                        }
                    ],
#                    "metric_relabel_configs": [
#                        {
#                            "source_labels": ["__name__"],
#                            "regex": "xray_.*",
#                            "action": "keep"
#                        }
#                    ],
                    "metrics_path": "/metrics"
                },
                {
                    "job_name": "v2ray-exporter",
                    "static_configs": [
                        {
                            "targets": [
                                "v2ray-exporter:9550"
                            ],
                            "labels": {
                                "donor": DONOR,
                                "instance": instance_ip
                            }
                        }
                    ],
                    "metric_relabel_configs": [
                        {
                            "source_labels": ["__name__"],
                            "regex": "go_.*",
                            "action": "drop"
                        },
                        {
                            "source_labels": ["__name__"],
                            "regex": "v2ray_memstats_.*",
                            "action": "drop"
                        },
                        {
                            "source_labels": ["__name__"],
                            "regex": "v2ray_scrape_.*",
                            "action": "drop"
                        },
                        {
                            "source_labels": ["__name__"],
                            "regex": "scrape_.*",
                            "action": "drop"
                        },
                        {
                            "source_labels": ["__name__"],
                            "regex": "promhttp_.*",
                            "action": "drop"
                        },
                    ],
                    "metrics_path": "/scrape"
                },
                {
                    "job_name": "user-metrics",
                    "static_configs": [
                        {
                            "targets": [
                                "user-metrics:9551"
                            ],
                            "labels": {
                                "donor": DONOR,
                                "instance": instance_ip
                            }
                        }
                    ],
#                    "metric_relabel_configs": [
#                        {
#                            "source_labels": ["__name__"],
#                            "regex": ".*",
#                            "action": "keep"
#                        }
#                    ],
                    "metrics_path": ""
                }
            ]
          }
        ]
      }
    }
    with open('config.yaml', 'w') as yaml_file:
        yaml.dump(config, yaml_file, default_flow_style=False)
