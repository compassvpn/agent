import json
import sys
import threading
import time
from typing import Dict, Optional, Union
from flask import Flask, abort
from werkzeug.serving import make_server

from config import config
from shared_lib.system import exec_command, get_machine_id, csv_to_dict
from shared_lib.logger import log, is_debug
from shared_lib.network import get_public_ip
from shared_lib.xray import parse_config_link
from shared_lib.paths import CONFIGS_CSV, VALID_CSV


def _prom_label_escape(value: object) -> str:
    """Escape a value for a Prometheus exposition-format label value.

    Label values must escape backslash, double-quote, and newline; otherwise an
    untrusted value such as the geo-IP-derived country (or a crafted config
    link) could corrupt the exposition output or inject extra labels/series.
    """
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class XrayService:
    def __init__(self) -> None:
        self.app: Flask = Flask(__name__)
        self.valid_configs: Dict[str, Dict[str, str]] = {}
        self.latest_metrics: str = ""
        self.instance_location_info: Optional[Union[str, Dict[str, str]]] = None
        self._shutdown_event: threading.Event = threading.Event()
        self._last_result: tuple = ()
        self._setup_routes()

    def _setup_routes(self) -> None:
        @self.app.route("/config")
        def get_xray_config():
            if not config.initialized:
                log.debug("Config requested before it's ready", cat="xray")
                return "Not Ready", 503
            # Strip top-level null keys; some Xray versions reject them
            clean = {k: v for k, v in config.xray_config.items() if v is not None}
            return json.dumps(clean, indent=4)

        @self.app.route("/subdomain")
        def export_certs():
            if not config.initialized or not config.direct_subdomain:
                log.debug("Subdomain requested before it's ready", cat="xray")
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

        @self.app.route("/nginx-locations")
        def get_nginx_locations():
            if not config.initialized:
                return "Not Ready", 503
            return json.dumps(config.nginx_locations, indent=4)

        @self.app.route("/metrics")
        def metrics():
            return self.latest_metrics

    def update_metrics(self, configs: Dict[str, Dict[str, str]]) -> bool:
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
        total_count = len(configs)
        failed_count = 0
        for config_link, value in configs.items():
            try:
                status = value["status"]
                delay = value["delay"]

                config_info = parse_config_link(config_link)
                labels = [
                    f'config_link="{_prom_label_escape(config_link)}"',
                    f'config_name="{_prom_label_escape(config_info["name"])}"',
                    f'machine_id="{_prom_label_escape(get_machine_id())}"',
                    f'ip="{_prom_label_escape(instance_ip)}"',
                    f'country="{_prom_label_escape(instance_country)}"',
                    f'config_protocol="{_prom_label_escape(config_info["protocol"])}"',
                    f'config_host="{_prom_label_escape(config_info["host"])}"',
                    f'config_port="{_prom_label_escape(config_info["port"])}"',
                    f'config_cipher="{_prom_label_escape(config_info["cipher"])}"',
                    f'config_security="{_prom_label_escape(config_info["security"])}"',
                    f'config_type="{_prom_label_escape(config_info["type"])}"',
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
                log.error("Couldn't build the metric for a config", cat="metrics", link=config_link, error=str(e))
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

    def _log_changed(self, level: str, msg: str, **kw: str) -> None:
        # The test loop repeats every few minutes; only speak up when the result changes.
        if (msg, kw) != self._last_result:
            self._last_result = (msg, kw)
            getattr(log, level)(msg, cat="test", **kw)

    def background_job(self) -> None:
        # Give xray a moment to fetch its config and start, or the first run
        # fails every config and logs a false alarm.
        if self._interruptible_sleep(15):
            return

        while not self._shutdown_event.is_set():
            if not config.initialized:
                if self._interruptible_sleep(5):
                    break
                continue

            valid_links = [
                link
                for link in config.get_config_links()
                if link.startswith(("vmess://", "vless://"))
            ]
            if not valid_links:
                self._log_changed("warning", "No vless/vmess links to test")
                if self._interruptible_sleep(60):
                    break
                continue

            with open(CONFIGS_CSV, "w", encoding="utf-8") as configs_csv:
                configs_csv.write("\n".join(valid_links))

            log.debug("Testing configs", cat="test", count=len(valid_links))
            knife_cmd = [
                "xray-knife",
                "http",
                "--threads",
                "6",
                "--mdelay",
                "10000",
                # One retry so a transient blip does not flap a config to down
                # for the whole cycle.
                "--retries",
                "1",
                # We only test vmess/vless; pin the core instead of auto-detect.
                "--core",
                "xray",
                # Skip the per-config real-IP lookup; unused (instance IP comes
                # from get_public_ip) and it adds a request per config.
                "--rip=false",
                "--file",
                str(CONFIGS_CSV),
                "--out",
                str(VALID_CSV),
                "--type",
                "csv",
            ]
            if is_debug():
                knife_cmd.append("--verbose")
            result = exec_command(knife_cmd, capture_output=not is_debug())

            self.valid_configs = csv_to_dict(str(VALID_CSV))
            failed = [
                f'{parse_config_link(link)["name"]} ({row.get("failure_kind") or row.get("reason") or "failed"})'
                for link, row in self.valid_configs.items()
                if row.get("status") != "passed"
            ]
            passed = f"{len(self.valid_configs) - len(failed)}/{len(self.valid_configs)}"
            if not self.valid_configs:
                self._log_changed("error", "xray-knife gave no results")
                sys.stderr.write((result.stdout or "") + (result.stderr or ""))
            elif failed:
                self._log_changed("warning", "Some configs failing", passed=passed, failed=", ".join(failed))
            else:
                self._log_changed("info", "All configs passing", passed=passed)

            success = bool(self.valid_configs) and self.update_metrics(self.valid_configs)
            sleep_duration = 300 if success else 15
            if self._interruptible_sleep(sleep_duration):
                break

    def cert_management_job(self) -> None:
        # initialize() already issued or renewed the cert at boot, so wait first.
        # Daily is cheap since acme.sh is a quiet no-op until renewal is due.
        while not self._shutdown_event.wait(timeout=86400):
            if not (config.cf_api_token and config.direct_subdomain):
                continue
            # 2 means it isn't due yet; run_acme logs real failures
            if config.run_acme(f"--renew --dns dns_cf -d {config.direct_subdomain}") != 0:
                continue
            # Bumps the served config so xray's hourly watcher reloads the cert
            if not config.reload_certs():
                log.error("Cert renewed, but xray keeps the old one until it restarts", cat="cert")
            # nginx watches this file and reloads when it changes
            try:
                with open("/var/log/compassvpn/.cert_renewed", "w", encoding="utf-8") as f:
                    f.write(str(time.time()))
            except OSError as e:
                log.error("Cert renewed, but couldn't tell nginx to reload", cat="cert", error=str(e))
            log.info("TLS cert renewed", cat="cert", domain=config.direct_subdomain)

    def run(self) -> None:
        config.initialize()

        thread = threading.Thread(target=self.background_job)
        thread.daemon = True
        thread.start()

        cert_thread = threading.Thread(target=self.cert_management_job)
        cert_thread.daemon = True
        cert_thread.start()

        # make_server skips the dev-server banner that app.run prints
        make_server("0.0.0.0", 5000, self.app, threaded=True).serve_forever()


if __name__ == "__main__":
    service = XrayService()
    service.run()
