import base64
import copy
import hashlib
import ipaddress
import json
import re
import string
from pathlib import Path
from datetime import datetime, timezone
from time import sleep
from typing import Any, Dict, List, Optional
from urllib.parse import unquote, quote
import requests

from shared_lib.network import get_public_ip
from shared_lib.xray import register_warp
from shared_lib.config import load_env, get_identifier
from shared_lib.system import exec_command
from shared_lib.logger import log, is_debug
from shared_lib.paths import (
    ACME_SH_PATH,
    INBOUNDS_JSON,
    XRAY_ACCESS_LOG,
    XRAY_ERROR_LOG,
)


# (connect, read) timeout for Cloudflare API calls so a network stall can't
# hang startup forever.
CF_API_TIMEOUT = (10, 30)


# Inbounds that bind a port directly (no HTTP path) — replicas not supported
_NO_REPLICA_SUPPORT = {"vless-tcp-tls-direct", "vless-tcp-reality-direct", "vless-xhttp-reality-direct"}

# Maps inbound name → (nginx server port, location template)
_NGINX_PROXY_MAP: Dict[str, tuple] = {
    "vless-hu-direct":         (8080, "hu"),
    "vless-hu-cdn":            (8080, "hu"),
    "vless-hu-tls-direct":     (2053, "hu"),
    "vless-hu-tls-cdn":        (2053, "hu"),
    "vless-xhttp-direct":      (8880, "xhttp"),
    "vless-xhttp-cdn":         (8880, "xhttp"),
    "vless-xhttp-quic-direct": (8443, "xhttp_quic"),
    "vless-xhttp-quic-cdn":    (8443, "xhttp_quic"),
}

_STREAM_PATH_KEY = {
    "ws":          "wsSettings",
    "httpupgrade": "httpupgradeSettings",
    "xhttp":       "xhttpSettings",
}


def _make_replica(inbound_def: Dict[str, Any], replica_index: int, new_port: int) -> Dict[str, Any]:
    replica = copy.deepcopy(inbound_def)
    suffix = f"/{replica_index}"

    replica["inbound"]["tag"] += f"-{replica_index}"
    replica["inbound"]["port"] = new_port

    stream = replica["inbound"].get("streamSettings", {})
    sk = _STREAM_PATH_KEY.get(stream.get("network", ""))
    if sk and sk in stream:
        stream[sk]["path"] += suffix

    link = replica.get("link")
    if isinstance(link, dict):
        if "path" in link:
            link["path"] += suffix
        if "ps" in link:
            link["ps"] += f"-{replica_index}"
    elif isinstance(link, str):
        replica["link"] = re.sub(
            r"path=([^&#]+)",
            lambda m: f"path={quote(unquote(m.group(1)) + suffix, safe='')}",
            link,
        )
        replica["link"] = re.sub(
            r"#(.+)$",
            lambda m: f"#{m.group(1)}-{replica_index}",
            replica["link"],
        )

    return replica


def _nginx_location_block(path: str, xray_port: int, template: str) -> str:
    if template == "hu":
        return (
            f'    location = {path} {{\n'
            f'        if ($http_upgrade != "websocket") {{ return 404; }}\n'
            f'        proxy_pass http://xray:{xray_port};\n'
            f'        proxy_http_version 1.1;\n'
            f'        proxy_set_header Upgrade $http_upgrade;\n'
            f'        proxy_set_header Connection "upgrade";\n'
            f'        proxy_set_header X-Real-IP $remote_addr;\n'
            f'        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n'
            f'        proxy_set_header Host $host;\n'
            f'        proxy_redirect off;\n'
            f'        proxy_read_timeout 315;\n'
            f'        proxy_socket_keepalive on;\n'
            f'    }}'
        )
    if template == "xhttp":
        return (
            f'    location {path} {{\n'
            f'        proxy_pass http://xray:{xray_port};\n'
            f'        proxy_http_version 1.1;\n'
            f'        proxy_set_header Host $host;\n'
            f'        proxy_set_header X-Real-IP $remote_addr;\n'
            f'        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n'
            f'        proxy_set_header Upgrade $http_upgrade;\n'
            f'        proxy_set_header Connection $connection_upgrade;\n'
            f'        proxy_buffering off;\n'
            f'        proxy_read_timeout 315;\n'
            f'    }}'
        )
    if template == "xhttp_quic":
        return (
            f'    location {path} {{\n'
            f'        grpc_pass grpc://xray:{xray_port};\n'
            f'        grpc_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n'
            f'        grpc_read_timeout 315;\n'
            f'        grpc_send_timeout 5m;\n'
            f'        client_body_timeout 5m;\n'
            f'        client_max_body_size 0;\n'
            f'    }}'
        )
    return ""


def _cert_not_after(cert_file: str) -> Optional[datetime]:
    """Return a PEM cert's notAfter (UTC), or None if it can't be determined."""
    result = exec_command(
        ["openssl", "x509", "-enddate", "-noout", "-in", cert_file],
        capture_output=True,
    )
    if result.returncode != 0 or not result.stdout:
        return None
    # stdout looks like: "notAfter=Jun 18 12:00:00 2026 GMT"
    raw = result.stdout.strip().split("=", 1)[-1].strip()
    try:
        return datetime.strptime(raw, "%b %d %H:%M:%S %Y %Z").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


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
        self.xray_inbounds: Dict[str, int] = {}
        self.server_ip: str = "Unknown"
        self.domain: Optional[str] = None
        self.subdomain: Optional[str] = None
        self.direct_subdomain: Optional[str] = None
        self._cert_serial: int = 0
        self.cf_clean_ip_domain: str = "npmjs.com"
        self.reality_private_key: str = ""
        self.reality_public_key: str = ""
        self.reality_sni: str = ""
        # VLESS Encryption (post-quantum AEAD) for the non-TLS httpupgrade
        # inbounds: derived deterministically like REALITY so links survive
        # redeploys. Empty until _setup_vless_encryption populates them.
        self.vless_enc_private_key: str = ""
        self.vless_enc_password: str = ""
        self.vless_enc_decryption: str = ""
        self.vless_enc_encryption: str = ""
        self.configured_inbounds: List[Dict[str, Any]] = []
        self.xray_config: Dict[str, Any] = {}
        self.warps_ready: bool = False
        self.wg_configs: Dict[str, str] = {}
        self.warps: List[Dict[str, Any]] = []
        self.nginx_locations: Dict[int, str] = {}
        self.initialized: bool = False

    def _get_domain(self) -> None:
        """Internal method to retrieve domain from Cloudflare API."""
        url = f"https://api.cloudflare.com/client/v4/zones/{self.cf_zone_id}"
        headers = {
            "Authorization": f"Bearer {self.cf_api_token}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.get(url, headers=headers, timeout=CF_API_TIMEOUT)
            log.debug(
                "get_domain response",
                hypothesisId="DNS",
                status=response.status_code,
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
                response = requests.get(url, headers=headers, timeout=CF_API_TIMEOUT)
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
                response = requests.post(endpoint, json=data, headers=headers, timeout=CF_API_TIMEOUT)
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

    def _setup_reality(self) -> None:
        """Derive the REALITY keypair and short id deterministically from the
        identifier (same idea as the uuid), so links survive redeploys without
        persisting any key material."""
        seed = hashlib.sha256(f"{self.config_id}:reality".encode()).digest()
        seed_b64 = base64.urlsafe_b64encode(seed).decode().rstrip("=")
        result = exec_command(["xray", "x25519", "-i", seed_b64], capture_output=True)
        if result.returncode != 0 or not result.stdout:
            log.error(
                "xray x25519 failed; REALITY inbounds will be skipped",
                hypothesisId="CFG",
                exit_code=result.returncode,
            )
            return
        # v26 prints "PrivateKey:" / "Password (PublicKey):"; older builds
        # printed "Private key:" / "Public key:" — accept both.
        for line in result.stdout.splitlines():
            label, _, value = line.partition(":")
            label = label.strip().lower()
            value = value.strip()
            if label in ("privatekey", "private key"):
                self.reality_private_key = value
            elif label.startswith("password") or label == "public key":
                self.reality_public_key = value
        if not self.reality_private_key or not self.reality_public_key:
            self.reality_private_key = self.reality_public_key = ""
            log.error(
                "Could not parse xray x25519 output; REALITY inbounds will be skipped",
                hypothesisId="CFG",
            )
            return

    def _setup_vless_encryption(self) -> None:
        """Derive the VLESS Encryption keypair deterministically from the
        identifier (same idea as REALITY) so the non-TLS httpupgrade links
        survive redeploys without persisting any key material.

        Authentication uses X25519 (the ephemeral exchange is ML-KEM-768 +
        X25519, so it stays post-quantum safe either way). The server keeps the
        private key in `decryption`; clients carry the matching public key
        ("Password") in `encryption`. Format per Xray-core:
          decryption: mlkem768x25519plus.xorpub.600s.<padding>.<PrivateKey>
          encryption: mlkem768x25519plus.xorpub.0rtt.<padding>.<Password>
        xorpub masks the handshake public key (cheap obfs against DPI); the
        default padding hides the handshake length. Client uses 0rtt for fast,
        battery-friendly reconnects.
        """
        seed = hashlib.sha256(f"{self.config_id}:vless-enc".encode()).digest()
        seed_b64 = base64.urlsafe_b64encode(seed).decode().rstrip("=")
        result = exec_command(["xray", "x25519", "-i", seed_b64], capture_output=True)
        if result.returncode != 0 or not result.stdout:
            log.error(
                "xray x25519 failed; VLESS-encryption inbounds will be skipped",
                hypothesisId="CFG",
                exit_code=result.returncode,
            )
            return
        # v26 prints "PrivateKey:" / "Password (PublicKey):"; older builds
        # printed "Private key:" / "Public key:" — accept both.
        for line in result.stdout.splitlines():
            label, _, value = line.partition(":")
            label = label.strip().lower()
            value = value.strip()
            if label in ("privatekey", "private key"):
                self.vless_enc_private_key = value
            elif label.startswith("password") or label == "public key":
                self.vless_enc_password = value
        if not self.vless_enc_private_key or not self.vless_enc_password:
            self.vless_enc_private_key = self.vless_enc_password = ""
            log.error(
                "Could not parse xray x25519 output; VLESS-encryption inbounds will be skipped",
                hypothesisId="CFG",
            )
            return
        # xorpub obfuscation + the stock padding profile (shared by everyone,
        # so it blends into the largest crowd rather than standing out).
        _padding = "100-111-1111.75-0-111.50-0-3333"
        self.vless_enc_decryption = (
            f"mlkem768x25519plus.xorpub.600s.{_padding}.{self.vless_enc_private_key}"
        )
        self.vless_enc_encryption = (
            f"mlkem768x25519plus.xorpub.0rtt.{_padding}.{self.vless_enc_password}"
        )

    def initialize(self) -> None:
        """Perform all initialization logic. Only executes once."""
        if self.initialized:
            return

        self.env_config = load_env()
        self.is_debug_enabled = is_debug()
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
        self.xray_inbounds = {}
        for entry in self.env_config.get(
            "XRAY_INBOUNDS",
            "vless-hu-direct,vless-hu-cdn,vless-tcp-tls-direct,vless-tcp-reality-direct,vless-xhttp-reality-direct,vless-hu-tls-direct,vless-hu-tls-cdn,vless-xhttp-quic-direct,vless-xhttp-quic-cdn,vless-xhttp-direct,vless-xhttp-cdn",
        ).split(","):
            name, _, count = entry.strip().partition(":")
            self.xray_inbounds[name] = int(count) if count.isdigit() else 1

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
                                    "Failed to issue SSL certificate; TLS inbounds will be skipped",
                                    hypothesisId="CERT",
                                )
                        else:
                            log.error(
                                "Failed to register ACME account; TLS inbounds will be skipped",
                                hypothesisId="CERT",
                            )

            else:
                log.debug("Domain not found, skipping records", hypothesisId="DNS")
        else:
            log.debug(
                "CF tokens missing or IP unknown, skipping DNS/SSL setup",
                hypothesisId="CFG",
            )

        self.cf_clean_ip_domain = self.env_config.get("CF_CLEAN_IP_DOMAIN", "npmjs.com")

        # REALITY needs no cert or nginx: its camouflage SNI reuses the same
        # decoy site nginx fronts (FAKE_WEBSITE). It must be a real TLS 1.3 +
        # X25519 site reachable from this server.
        self.reality_sni = self.env_config.get("FAKE_WEBSITE", "www.divar.ir")
        self._setup_reality()
        self._setup_vless_encryption()

        # Process Inbounds Template
        def substitute_vars(data: Any, mapping: Dict[str, Any]) -> Any:
            """Recursively substitute variables in strings within a nested data structure."""
            if isinstance(data, dict):
                return {k: substitute_vars(v, mapping) for k, v in data.items()}
            elif isinstance(data, list):
                return [substitute_vars(i, mapping) for i in data]
            elif isinstance(data, str):
                return string.Template(data).safe_substitute(mapping)
            return data

        with open(INBOUNDS_JSON, encoding="utf-8") as f:
            raw_inbounds = json.load(f)
            all_inbounds = substitute_vars(
                raw_inbounds,
                {
                    "config_id": self.config_id,
                    "config_uuid": self.config_uuid,
                    "cf_clean_ip_domain": self.cf_clean_ip_domain,
                    "nginx_path": self.nginx_path,
                    "server_ip": self.server_ip,
                    "direct_subdomain": self.direct_subdomain or "",
                    "subdomain": self.subdomain or "",
                    "reality_private_key": self.reality_private_key,
                    "reality_public_key": self.reality_public_key,
                    "reality_sni": self.reality_sni,
                    "vless_enc_decryption": self.vless_enc_decryption,
                    "vless_enc_encryption": self.vless_enc_encryption,
                },
            )
            self.configured_inbounds = [
                ib for ib in all_inbounds if ib.get("name") in self.xray_inbounds
            ]

            # Expand replicas. Indices start at 1: replica 1 keeps the original
            # port (matched by static nginx location blocks), replicas 2+ get
            # ports from the 9000+ pool.
            expanded: List[Dict[str, Any]] = []
            _replica_port = 9000
            for ib in self.configured_inbounds:
                name = ib.get("name", "")
                count = self.xray_inbounds.get(name, 1)
                if name in _NO_REPLICA_SUPPORT and count > 1:
                    log.warning(
                        f"{name} does not support replicas; capped at 1",
                        hypothesisId="CFG",
                    )
                    count = 1
                for idx in range(1, count + 1):
                    port = ib["inbound"]["port"] if idx == 1 else _replica_port
                    if idx > 1:
                        _replica_port += 1
                    replica = _make_replica(ib, idx, port)
                    replica["_replica_index"] = idx
                    if name in _NGINX_PROXY_MAP:
                        replica["_nginx_port"], replica["_nginx_template"] = _NGINX_PROXY_MAP[name]
                    expanded.append(replica)
                if count > 1:
                    log.info(f"{name}: {count} replicas configured", hypothesisId="CFG")
            self.configured_inbounds = expanded

        # Drop any inbound whose TLS cert/key resolved to an empty string after
        # variable substitution. An empty cert would make `xray -test` fail and
        # bring down the whole container.
        warned_certs: set = set()

        def _has_valid_tls(inbound_def: Dict[str, Any]) -> bool:
            stream = inbound_def.get("inbound", {}).get("streamSettings", {})
            if stream.get("security") != "tls":
                return True
            for cert_entry in stream.get("tlsSettings", {}).get("certificates", []):
                cert_file = cert_entry.get("certificateFile", "")
                key_file = cert_entry.get("keyFile", "")
                if not cert_file or not key_file:
                    return False
                if not Path(cert_file).exists() or not Path(key_file).exists():
                    return False
                # Don't silently serve an expired cert (renewal may be failing).
                not_after = _cert_not_after(cert_file)
                if not_after is not None:
                    days_left = (not_after - datetime.now(timezone.utc)).days
                    if days_left < 0:
                        if cert_file not in warned_certs:
                            warned_certs.add(cert_file)
                            log.error(
                                "TLS cert is EXPIRED; skipping its inbound(s) - "
                                "renewal is failing, check the CF token / acme.sh logs",
                                hypothesisId="CERT",
                                cert=cert_file,
                                not_after=not_after.isoformat(),
                            )
                        return False
                    if days_left < 14 and cert_file not in warned_certs:
                        warned_certs.add(cert_file)
                        log.warning(
                            "TLS cert expires soon; renewal may be failing",
                            hypothesisId="CERT",
                            cert=cert_file,
                            days_left=days_left,
                        )
            return True

        before = len(self.configured_inbounds)
        self.configured_inbounds = [ib for ib in self.configured_inbounds if _has_valid_tls(ib)]
        skipped = before - len(self.configured_inbounds)
        if skipped:
            log.warning(
                f"Skipped {skipped} TLS inbound(s) with missing certificates",
                hypothesisId="CFG",
            )

        # Same idea for REALITY: an empty privateKey would fail `xray -test`
        # and bring down the whole container.
        if not self.reality_private_key:
            before = len(self.configured_inbounds)
            self.configured_inbounds = [
                ib for ib in self.configured_inbounds
                if ib.get("inbound", {}).get("streamSettings", {}).get("security") != "reality"
            ]
            skipped = before - len(self.configured_inbounds)
            if skipped:
                log.warning(
                    f"Skipped {skipped} REALITY inbound(s): key generation failed",
                    hypothesisId="CFG",
                )

        # Same idea for VLESS Encryption: an empty decryption string would fail
        # `xray -test` and bring down the whole container.
        if not self.vless_enc_decryption:
            before = len(self.configured_inbounds)
            self.configured_inbounds = [
                ib for ib in self.configured_inbounds
                if not ib.get("inbound", {})
                .get("settings", {})
                .get("decryption", "")
                .startswith("mlkem768x25519plus")
            ]
            skipped = before - len(self.configured_inbounds)
            if skipped:
                log.warning(
                    f"Skipped {skipped} VLESS-encryption inbound(s): key generation failed",
                    hypothesisId="CFG",
                )

        # Build nginx location blocks for replicas that survived TLS filtering
        nginx_locs: Dict[int, List[str]] = {}
        for ib in self.configured_inbounds:
            if ib.get("_replica_index", 0) > 1 and "_nginx_port" in ib:
                stream = ib["inbound"].get("streamSettings", {})
                sk = _STREAM_PATH_KEY.get(stream.get("network", ""))
                path = stream.get(sk, {}).get("path", "") if sk else ""
                if path:
                    block = _nginx_location_block(path, ib["inbound"]["port"], ib["_nginx_template"])
                    nginx_locs.setdefault(ib["_nginx_port"], []).append(block)
        self.nginx_locations = {port: "\n\n".join(blocks) for port, blocks in nginx_locs.items()}

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
            "_cert_serial": self._cert_serial,
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
                ("https+local://", "quic+local://", "tls+local://")
            ):
                dns_server = custom_dns_config
            else:
                # Plain UDP resolver, must be a valid IPv4 address
                try:
                    ipaddress.IPv4Address(custom_dns_config)
                    dns_server = custom_dns_config
                except ValueError:
                    pass
            if dns_server:
                self.xray_config["dns"] = {
                    "servers": [dns_server],
                    "queryStrategy": "UseIPv4",
                }
            else:
                log.warning(
                    f"CUSTOM_DNS value {custom_dns_config!r} is not a supported format; using default DNS",
                    hypothesisId="CFG",
                )

        # WARP configuration
        self.warps_ready = False
        self.wg_configs = {}
        warp_active = False
        active_inbounds = [
            ib for ib in self.configured_inbounds
            if "inbound" in ib and "tag" in ib["inbound"]
        ]
        if self.env_config.get("XRAY_OUTBOUND") == "warp":
            try:
                self.warps = []
                for i in range(len(active_inbounds)):
                    if i > 0:
                        sleep(2)
                    self.warps.append(register_warp())
                self.warps_ready = True
                warp_active = True
            except Exception as e:
                log.error(
                    "WARP registration failed; falling back to direct outbound",
                    hypothesisId="WARP",
                    error=str(e),
                )

        if warp_active:
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

            self.xray_config["routing"]["domainStrategy"] = "IPOnDemand"

            for i, ib in enumerate(active_inbounds):
                tag = ib["inbound"]["tag"]
                self.xray_config["routing"]["rules"].insert(
                    i,
                    {
                        "inboundTag": [tag],
                        "outboundTag": f"warp{i}",
                    },
                )

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

        if not active_inbounds:
            log.warning(
                "No user-facing inbounds are active. "
                "Clients will not be able to connect. "
                "Check CF credentials, TLS cert availability, and XRAY_INBOUNDS.",
                hypothesisId="CFG",
            )
        else:
            tags = [ib["inbound"]["tag"] for ib in active_inbounds]
            log.info(
                f"Initialized with {len(active_inbounds)} active inbound(s): {', '.join(tags)}",
                hypothesisId="CFG",
            )

        self.initialized = True

    def reload_certs(self) -> bool:
        """Bump cert serial so the config watcher detects a change and SIGHUPs xray to reload cert files."""
        if not self.direct_subdomain:
            return False
        cert_path = ACME_SH_PATH / f"{self.direct_subdomain}_ecc" / "fullchain.cer"
        key_path = ACME_SH_PATH / f"{self.direct_subdomain}_ecc" / f"{self.direct_subdomain}.key"
        if not cert_path.exists() or not key_path.exists():
            log.error("reload_certs: cert files not found after renewal", hypothesisId="CERT")
            return False
        self._cert_serial += 1
        self.xray_config["_cert_serial"] = self._cert_serial
        return True

    def get_config_links(self) -> List[str]:
        """Return formatted config links for active inbounds."""
        configs: List[str] = []
        # CF inbounds need a subdomain to form a valid link
        if self.subdomain:
            configs.extend(
                [
                    inbound.get("link", "")
                    for inbound in self.configured_inbounds
                    if inbound.get("cloudflare", False)
                ]
            )
        # Direct inbounds are always testable if they made it into configured_inbounds
        configs.extend(
            [
                inbound.get("link", "")
                for inbound in self.configured_inbounds
                if inbound.get("cloudflare", False) is False
            ]
        )
        return [link for link in configs if link]


# Singleton instance for structured access
config = XrayConfig()
