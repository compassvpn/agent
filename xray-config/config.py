import json
import os
import string
import sys
from time import sleep
from typing import Any, Dict, List, Optional
import requests

# Add root to sys.path to allow importing shared_lib
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from shared_lib.network import get_public_ip
from shared_lib.xray import register_warp, generate_vmess_link
from shared_lib.config import load_env, get_identifier
from shared_lib.system import exec_command
from shared_lib.logger import log
from shared_lib.paths import (
    ACME_SH_PATH,
    INBOUNDS_JSON,
    XRAY_ACCESS_LOG,
    XRAY_ERROR_LOG,
)


class XrayConfig:
    def __init__(self) -> None:
        """Initialize instance attributes to hold shared variables."""
        self.env_config: Dict[str, str] = {}
        self.is_debug_enabled: bool = False
        self.config_id: str = ""
        self.config_uuid: str = ""
        self.cf_api_token: Optional[str] = None
        self.cf_zone_id: Optional[str] = None
        self.nginx_path: Optional[str] = None
        self.xray_inbounds: List[str] = []
        self.server_ip: str = "Unknown"
        self.domain: Optional[str] = None
        self.subdomain: Optional[str] = None
        self.direct_subdomain: Optional[str] = None
        self.cert_public: str = ""
        self.cert_private: str = ""
        self.cf_clean_ip_domain: str = "npmjs.com"
        self.configured_inbounds: List[Dict[str, Any]] = []
        self.xray_config: Dict[str, Any] = {}
        self.warps_ready: bool = False
        self.wg_configs: Dict[str, str] = {}
        self.warps: List[Dict[str, Any]] = []
        self.initialized: bool = False

    def _get_domain(self) -> None:
        """Internal method to retrieve domain from Cloudflare API."""
        url = f"https://api.cloudflare.com/client/v4/zones/{self.cf_zone_id}"
        headers = {
            "Authorization": f"Bearer {self.cf_api_token}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.get(url, headers=headers)
            log.debug(
                "get_domain response",
                hypothesisId="DNS",
                status=response.status_code,
                body=response.text[:200],
            )
            if response.status_code == 200:
                self.domain = response.json()["result"]["name"]
                log.info(
                    f"The domain name associated with zone ID {self.cf_zone_id} is: {self.domain}",
                    hypothesisId="DNS",
                )
            else:
                log.error(
                    f"Failed to retrieve domain name. Status code: {response.status_code}",
                    hypothesisId="DNS",
                    body=response.text[:200],
                )
        except Exception as e:
            log.error("get_domain error", hypothesisId="DNS", error=str(e))

    def _create_cf_records(self) -> Optional[str]:
        """Internal method to manage Cloudflare DNS records."""
        log.debug("Starting create_cf_records", hypothesisId="DNS")

        def dns_record_already_exist(record_name: str) -> Optional[bool]:
            url = f"https://api.cloudflare.com/client/v4/zones/{self.cf_zone_id}/dns_records?type=A&name={record_name}.{self.domain}"
            headers = {
                "Authorization": f"Bearer {self.cf_api_token}",
                "Content-Type": "application/json",
            }
            try:
                response = requests.get(url, headers=headers)
                log.debug(
                    f"Check DNS {record_name}",
                    hypothesisId="DNS",
                    status=response.status_code,
                )
                if response.status_code == 200:
                    dns_records = response.json()["result"]
                    return bool(dns_records)
            except Exception as e:
                log.error(
                    f"Check DNS error {record_name}", hypothesisId="DNS", error=str(e)
                )
            return None

        def create_dns_record(name: str, proxied: bool) -> Optional[str]:
            endpoint = f"https://api.cloudflare.com/client/v4/zones/{self.cf_zone_id}/dns_records"
            if dns_record_already_exist(name):
                return name
            data = {
                "type": "A",
                "name": name,
                "content": self.server_ip,
                "ttl": 1,
                "proxied": proxied,
            }
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.cf_api_token}",
            }
            try:
                response = requests.post(endpoint, json=data, headers=headers)
                if response.status_code == 200:
                    log.debug(
                        "Create DNS result",
                        name=name,
                        status=response.status_code,
                        hypothesisId="DNS",
                    )
                    return name
                else:
                    log.error(
                        "Create DNS failed",
                        name=name,
                        status=response.status_code,
                        body=response.text[:200],
                        hypothesisId="DNS",
                    )
            except Exception as e:
                log.error(f"Create DNS error {name}", hypothesisId="DNS", error=str(e))
            return None

        server_ip_str = str(self.server_ip)
        name = get_identifier() + "-" + server_ip_str.replace(".", "")
        res1 = create_dns_record(name + "-direct", False)
        res2 = create_dns_record(name, True)
        return name if res1 and res2 else None

    def initialize(self) -> None:
        """Perform all initialization logic. Only executes once."""
        if self.initialized:
            return

        self.env_config = load_env()
        self.is_debug_enabled = self.env_config.get("DEBUG", "false").lower() == "true"
        log.debug(
            "Loaded env_config", hypothesisId="CFG", keys=list(self.env_config.keys())
        )

        self.config_id = get_identifier()
        log.debug("Identifier", hypothesisId="CFG", id=self.config_id)

        uuid_res = exec_command(
            ["xray", "uuid", "-i", self.config_id], capture_output=True
        )
        self.config_uuid = uuid_res.stdout.strip() if uuid_res.returncode == 0 else ""

        self.cf_api_token = self.env_config.get("CF_API_TOKEN")
        self.cf_zone_id = self.env_config.get("CF_ZONE_ID")
        self.nginx_path = self.env_config.get("NGINX_PATH")
        self.xray_inbounds = self.env_config.get(
            "XRAY_INBOUNDS",
            "vmess-ws-cdn,vless-tcp-tls-direct,vless-hu-tls-direct,vless-hu-tls-cdn,vless-xhttp-quic-direct,vless-xhttp-quic-cdn,vless-xhttp-direct,vless-xhttp-cdn",
        ).split(",")

        log.debug(
            "CF Config",
            hypothesisId="CFG",
            has_token=bool(self.cf_api_token),
            has_zone=bool(self.cf_zone_id),
        )

        self.server_ip = self.env_config.get("SERVER_IP", "")
        if not self.server_ip:
            server_ip_raw = get_public_ip()
            if isinstance(server_ip_raw, dict):
                self.server_ip = server_ip_raw.get("ip", "Unknown")
            else:
                self.server_ip = str(server_ip_raw) if server_ip_raw else "Unknown"

        log.debug("Server IP", hypothesisId="NET", ip=self.server_ip)

        # DNS and ACME Logic
        if self.cf_api_token and self.cf_zone_id and self.server_ip != "Unknown":
            self._get_domain()
            if self.domain:
                a_record = self._create_cf_records()
                if a_record:
                    self.subdomain = f"{a_record}.{self.domain}"
                    self.direct_subdomain = f"{a_record}-direct.{self.domain}"
                    log.debug(
                        "Subdomains set",
                        hypothesisId="DNS",
                        sub=self.subdomain,
                        direct=self.direct_subdomain,
                    )

                    ssl_provider = self.env_config.get("SSL_PROVIDER", "letsencrypt")
                    ssl_provider_server = (
                        "--server letsencrypt"
                        if ssl_provider == "letsencrypt"
                        else "--server zerossl"
                    )

                    acme_bin = f"{ACME_SH_PATH}/acme.sh"

                    def run_acme(cmd_args: str) -> bool:
                        import shlex

                        cmd_list = [acme_bin] + shlex.split(cmd_args)
                        result = exec_command(
                            cmd_list,
                            env={"CF_Token": self.cf_api_token or ""},
                        )
                        if result.returncode != 0:
                            log.error(
                                "acme.sh command failed",
                                exit_code=result.returncode,
                                cmd=" ".join(cmd_list),
                            )
                            return False
                        return True

                    cert_path = (
                        ACME_SH_PATH / f"{self.direct_subdomain}_ecc" / "fullchain.cer"
                    )
                    if cert_path.exists():
                        log.debug("Cert exists, renewing", hypothesisId="CERT")
                        run_acme(
                            f"{ssl_provider_server} --renew --dns dns_cf -d {self.direct_subdomain}"
                        )
                    else:
                        log.debug("Cert missing, issuing", hypothesisId="CERT")
                        if run_acme(
                            f"{ssl_provider_server} --register-account -m my@email.com"
                        ):
                            if not run_acme(
                                f"{ssl_provider_server} --issue --dns dns_cf -d {self.direct_subdomain}"
                            ):
                                log.error(
                                    "Failed to issue SSL certificate during bootstrap",
                                    hypothesisId="CERT",
                                )
                                return
                        else:
                            log.error(
                                "Failed to register ACME account during bootstrap",
                                hypothesisId="CERT",
                            )
                            return

                    try:
                        with open(cert_path, "r") as file:
                            self.cert_public = file.read()
                            self.cert_public = json.dumps(self.cert_public)[1:-1]
                        with open(
                            ACME_SH_PATH
                            / f"{self.direct_subdomain}_ecc"
                            / f"{self.direct_subdomain}.key",
                            "r",
                        ) as file:
                            self.cert_private = file.read()
                            self.cert_private = json.dumps(self.cert_private)[1:-1]
                        log.debug("Certs loaded successfully", hypothesisId="CERT")
                    except Exception as e:
                        log.error(
                            "Failed to load SSL certificates",
                            hypothesisId="CERT",
                            error=str(e),
                        )
                        return
            else:
                log.debug("Domain not found, skipping records", hypothesisId="DNS")
        else:
            log.debug(
                "CF tokens missing or IP unknown, skipping DNS/SSL setup",
                hypothesisId="CFG",
            )

        self.cf_clean_ip_domain = self.env_config.get("CF_CLEAN_IP_DOMAIN", "npmjs.com")

        # Process Inbounds Template
        with open(INBOUNDS_JSON) as f:
            inbound_template = string.Template(f.read())
            all_inbounds = json.loads(
                inbound_template.substitute(
                    {
                        "config_id": self.config_id,
                        "config_uuid": self.config_uuid,
                        "cf_clean_ip_domain": self.cf_clean_ip_domain,
                        "nginx_path": self.nginx_path,
                        "server_ip": self.server_ip,
                        "direct_subdomain": self.direct_subdomain or "",
                        "subdomain": self.subdomain or "",
                        "cert_public": self.cert_public or "",
                        "cert_private": self.cert_private or "",
                    }
                )
            )
            self.configured_inbounds = [
                inbound
                for inbound in all_inbounds
                if inbound.get("name") in self.xray_inbounds
            ]
            for inbound in self.configured_inbounds:
                if isinstance(inbound.get("link"), dict):
                    inbound["link"] = generate_vmess_link(inbound["link"])

        inbounds_list = [
            {
                "listen": "0.0.0.0",
                "port": 54321,
                "protocol": "dokodemo-door",
                "settings": {"address": "127.0.0.1"},
                "tag": "doko",
            }
        ]
        if self.cf_api_token and self.cf_zone_id:
            inbounds_list.extend(
                [
                    inbound["inbound"]
                    for inbound in self.configured_inbounds
                    if inbound.get("cloudflare", False) is True and "inbound" in inbound
                ]
            )

        inbounds_list.extend(
            [
                inbound["inbound"]
                for inbound in self.configured_inbounds
                if inbound.get("cloudflare", False) is False and "inbound" in inbound
            ]
        )

        self.xray_config = {
            "log": {
                "access": str(XRAY_ACCESS_LOG),
                "error": str(XRAY_ERROR_LOG),
                "loglevel": "debug" if self.is_debug_enabled else "warning",
                "dnsLog": self.is_debug_enabled,
            },
            "routing": {
                "domainStrategy": "AsIs",
                "rules": [
                    {"inboundTag": ["doko"], "outboundTag": "api"},
                    {
                        "outboundTag": "blocked",
                        "ip": [
                            "geoip:private",
                            "ext:geoip_IR.dat:ir",
                            "ext:geoip_IR.dat:phishing",
                            "ext:geoip_IR.dat:malware",
                        ],
                    },
                    {"outboundTag": "blocked", "protocol": ["bittorrent"]},
                    {
                        "outboundTag": "blocked",
                        "domain": [
                            "geosite:private",
                            "regexp:.*\\.ir$",
                            "regexp:.*\\.xn--mgba3a4f16a$",
                            "ext:geosite_IR.dat:ir",
                            "ext:geosite_IR.dat:category-ads-all",
                            "ext:geosite_IR.dat:malware",
                            "ext:geosite_IR.dat:phishing",
                            "ext:geosite_IR.dat:cryptominers",
                        ],
                    },
                ],
            },
            "dns": None,
            "inbounds": inbounds_list,
            "outbounds": [],
            "transport": None,
            "policy": {
                "levels": {"0": {"statsUserDownlink": True, "statsUserUplink": True}},
                "system": {"statsInboundDownlink": True, "statsInboundUplink": True},
            },
            "api": {
                "tag": "api",
                "services": ["HandlerService", "LoggerService", "StatsService"],
            },
            "stats": {},
            "reverse": None,
            "fakeDns": None,
        }

        # Custom DNS configuration
        custom_dns_config = self.env_config.get("CUSTOM_DNS", "default")
        if custom_dns_config != "default":
            dns_server = None
            if custom_dns_config == "cf":
                dns_server = "https+local://security.cloudflare-dns.com/dns-query"
            elif custom_dns_config == "controld":
                dns_server = "https+local://freedns.controld.com/no-ads-dating-drugs-gambling-malware-typo"
            elif custom_dns_config.startswith(
                "https+local://"
            ) or custom_dns_config.startswith("quic+local://"):
                dns_server = custom_dns_config
            if dns_server:
                self.xray_config["dns"] = {
                    "servers": [dns_server],
                    "queryStrategy": "UseIPv4",
                }

        # WARP configuration
        self.warps_ready = False
        self.wg_configs = {}
        if self.env_config.get("XRAY_OUTBOUND") == "warp":
            try:
                self.warps = []
                self.warps.append(register_warp())
                sleep(2)
                self.warps.append(register_warp())
                sleep(2)
                self.warps.append(register_warp())
                self.warps_ready = True
            except Exception as e:
                log.error("WARP registration failed during bootstrap", hypothesisId="WARP", error=str(e))
                return

            for i, warp in enumerate(self.warps):
                addresses = (
                    ", ".join(warp["addresses"]) if warp.get("addresses") else ""
                )
                self.wg_configs[f"wg{i}"] = f"""[Interface]
PrivateKey = {warp["privatekey"]}
Address = {addresses}
DNS = 1.1.1.1
MTU = 1280
Table = off

[Peer]
PublicKey = {warp["pubkey"]}
AllowedIPs = 0.0.0.0/0, ::/0
Endpoint = engage.cloudflareclient.com:2408
"""

            inbound_tags = [
                ib["inbound"]["tag"]
                for ib in self.configured_inbounds
                if "inbound" in ib and "tag" in ib["inbound"]
            ]
            self.xray_config["routing"]["rules"].insert(
                0,
                {
                    "inboundTag": inbound_tags,
                    "balancerTag": "balancer1",
                },
            )

            self.xray_config["routing"]["domainStrategy"] = "IPOnDemand"
            self.xray_config["routing"]["balancers"] = [
                {
                    "tag": "balancer1",
                    "selector": ["warp0", "warp1", "warp2"],
                    "strategy": {"type": "roundRobin"},
                }
            ]

            for i, warp in enumerate(self.warps):
                self.xray_config["outbounds"].append(
                    {
                        "tag": f"warp{i}",
                        "protocol": "freedom",
                        "settings": {"domainStrategy": "UseIPv4"},
                        "streamSettings": {
                            "sockopt": {"tcpFastOpen": True, "interface": f"wg{i}"}
                        },
                    }
                )

            self.xray_config["outbounds"].append(
                {
                    "tag": "direct",
                    "protocol": "freedom",
                    "settings": {"domainStrategy": "UseIPv4"},
                }
            )
        else:
            self.xray_config["outbounds"].append(
                {
                    "tag": "direct",
                    "protocol": "freedom",
                    "settings": {"domainStrategy": "UseIPv4"},
                }
            )

        self.xray_config["outbounds"] += [
            {"tag": "blocked", "protocol": "blackhole", "settings": {}}
        ]

        self.initialized = True

    def get_config_links(self) -> List[str]:
        """Return formatted config links for active inbounds."""
        configs: List[str] = []
        if self.subdomain:
            configs.extend(
                [
                    inbound.get("link", "")
                    for inbound in self.configured_inbounds
                    if inbound.get("cloudflare", False)
                ]
            )
            configs.extend(
                [
                    inbound.get("link", "")
                    for inbound in self.configured_inbounds
                    if inbound.get("cloudflare", False) is False
                ]
            )
        return configs


# Singleton instance for structured access
config = XrayConfig()
