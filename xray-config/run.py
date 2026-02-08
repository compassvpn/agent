import json
import os
import threading
import sys
from typing import Dict, List, Optional, Union
from flask import Flask, abort

# Add root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from config import config
from shared_lib.system import exec_command, get_machine_id, csv_to_dict
from shared_lib.logger import log
from shared_lib.network import get_public_ip
from shared_lib.xray import parse_config_link
from shared_lib.paths import CONFIGS_CSV, VALID_CSV, ACME_SH_PATH


class XrayService:
    def __init__(self) -> None:
        self.app: Flask = Flask(__name__)
        self.valid_configs: Dict[str, List[str]] = {}
        self.latest_metrics: str = ""
        self.instance_location_info: Optional[Union[str, Dict[str, str]]] = None
        self._shutdown_event: threading.Event = threading.Event()
        self._setup_routes()

    def _setup_routes(self) -> None:
        @self.app.route("/config")
        def get_xray_config():
            if not config.initialized:
                log.info(
                    "Xray Config requested but not yet initialized", hypothesisId="XRAY"
                )
                return "Not Ready", 503
            return json.dumps(config.xray_config, indent=4)

        @self.app.route("/valid-configs")
        def valid_configs_route():
            return json.dumps(self.valid_configs, indent=4)

        @self.app.route("/subdomain")
        def export_certs():
            if not config.initialized or not config.direct_subdomain:
                log.info("Subdomain requested but not yet ready", hypothesisId="XRAY")
                return "Not Ready", 503
            return config.direct_subdomain

        @self.app.route("/warps")
        def get_warps():
            if not config.warps_ready:
                abort(404)
            return json.dumps(config.warps, indent=4)

        @self.app.route("/wg-configs")
        def get_wg_configs():
            if not config.warps_ready:
                abort(404)
            return json.dumps(config.wg_configs, indent=4)

        @self.app.route("/metrics")
        def metrics():
            return self.latest_metrics

    def update_metrics(self, configs: Dict[str, List[str]]) -> bool:
        if not self.instance_location_info:
            self.instance_location_info = get_public_ip(extra=True)

        if isinstance(self.instance_location_info, dict):
            instance_ip = self.instance_location_info.get("ip", "Unknown")
            instance_country = self.instance_location_info.get("country", "Unknown")
        else:
            instance_ip = (
                str(self.instance_location_info)
                if self.instance_location_info
                else "Unknown"
            )
            instance_country = "Unknown"

        metrics = []
        total_count = len(configs.values())
        failed_count = 0
        for config_link, value in configs.items():
            try:
                status = value[1]
                delay = value[5]

                config_info = parse_config_link(config_link)
                labels = [
                    f'config_link="{config_link}"',
                    f'machine_id="{get_machine_id()}"',
                    f'ip="{instance_ip}"',
                    f'country="{instance_country}"',
                    f'config_protocol="{config_info["protocol"]}"',
                    f'config_host="{config_info["host"]}"',
                    f'config_port="{config_info["port"]}"',
                    f'config_security="{config_info["security"]}"',
                    f'config_type="{config_info["type"]}"',
                ]
                inline_labels = ",".join(labels)
                t = f"vpn_config{{{inline_labels}}}"

                if status == "passed":
                    t += f" {delay}"
                else:
                    failed_count += 1
                    t += " -1"
                metrics.append(t)
            except Exception as e:
                log.error(
                    f"Error processing config link {config_link}: {e}",
                    hypothesisId="METRIC",
                )
                continue

        self.latest_metrics = (
            "# HELP vpn_config vpn config up(working) or down(not working).\n"
            "# TYPE vpn_config gauge\n" + "\n".join(metrics) + "\n"
        )

        if failed_count == total_count and total_count > 0:
            return False
        return True

    def _interruptible_sleep(self, seconds: int) -> bool:
        """Sleep for `seconds`, returns True if shutdown requested."""
        return self._shutdown_event.wait(timeout=seconds)

    def background_job(self) -> None:
        log.info("start bg job", hypothesisId="TEST")

        while not self._shutdown_event.is_set():
            if not config.initialized:
                if self._interruptible_sleep(5):
                    break
                continue

            config_links = config.get_config_links()
            if not config_links:
                log.info("No config links found, waiting...", hypothesisId="TEST")
                if self._interruptible_sleep(60):
                    break
                continue

            valid_links = [
                link
                for link in config_links
                if link.startswith(("vmess://", "vless://"))
            ]

            if not valid_links:
                log.info(
                    "No valid vmess/vless links found, waiting...", hypothesisId="TEST"
                )
                if self._interruptible_sleep(60):
                    break
                continue

            with open(CONFIGS_CSV, "w") as configs_csv:
                configs_csv.write("\n".join(valid_links))

            exec_command(["cat", str(CONFIGS_CSV)])

            log.info("start xray testing...", hypothesisId="TEST")
            exec_command(
                [
                    "xray-knife",
                    "net",
                    "http",
                    "--thread",
                    "1",
                    "-d",
                    "30000",
                    "-r",
                    "-e",
                    "-p",
                    "-a",
                    "1000",
                    "-f",
                    str(CONFIGS_CSV),
                    "--type",
                    "csv",
                ]
            )

            self.valid_configs = csv_to_dict(str(VALID_CSV))
            log.debug(
                "Valid configs from CSV",
                hypothesisId="TEST",
                count=len(self.valid_configs),
                keys=list(self.valid_configs.keys()),
            )

            success = True
            if self.valid_configs:
                success = self.update_metrics(self.valid_configs)
            else:
                log.info(
                    "No valid configurations found after testing.", hypothesisId="TEST"
                )
                success = False

            log.info(f"xray test done - success: {success}", hypothesisId="TEST")

            sleep_duration = 300 if success else 15
            if self._interruptible_sleep(sleep_duration):
                break

        log.info("Background job shutting down", hypothesisId="TEST")

    def cert_management_job(self) -> None:
        while not self._shutdown_event.is_set():
            if not config.initialized:
                if self._shutdown_event.wait(timeout=5):
                    break
                continue

            if config.cf_api_token and config.direct_subdomain:
                exec_command(
                    [
                        str(ACME_SH_PATH / "acme.sh"),
                        "--renew",
                        "--dns",
                        "dns_cf",
                        "-d",
                        config.direct_subdomain,
                    ],
                    env={"CF_Token": config.cf_api_token or ""},
                )
                # 30-day sleep, interruptible
                if self._shutdown_event.wait(timeout=86400 * 30):
                    break
            else:
                if self._shutdown_event.wait(timeout=60):
                    break
        log.info("Cert management job shutting down", hypothesisId="CERT")

    def run(self) -> None:
        config.initialize()

        thread = threading.Thread(target=self.background_job)
        thread.daemon = True
        thread.start()

        cert_thread = threading.Thread(target=self.cert_management_job)
        cert_thread.daemon = True
        cert_thread.start()

        self.app.run(host="0.0.0.0", port=5000, debug=False)


if __name__ == "__main__":
    service = XrayService()
    service.run()
