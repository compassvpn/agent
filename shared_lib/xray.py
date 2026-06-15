import json
import base64
import subprocess
import requests
import time
from urllib.parse import urlparse, parse_qs
from typing import Dict, Any, Tuple
from shared_lib.logger import log


def parse_config_link(link: str) -> Dict[str, Any]:
    """
    Parses Xray config links (vmess, vless).
    Standardized to return 'id' as the primary identifier (consistent across protocols).
    """
    if link.startswith("vmess://"):
        b64_data = link[8:]
        # Fix padding if necessary
        missing_padding = len(b64_data) % 4
        if missing_padding:
            b64_data += "=" * (4 - missing_padding)
        try:
            decoded = base64.b64decode(b64_data).decode("utf-8")
            data = json.loads(decoded)
            return {
                "protocol": "vmess",
                "host": data.get("add"),
                "port": data.get("port"),
                "id": data.get("id"),
                "security": data.get("scy", "auto"),
                "type": data.get("net", "tcp"),
                "name": data.get("ps", ""),
            }
        except Exception as e:
            raise ValueError(f"Failed to decode vmess link: {e}")
    elif link.startswith("vless://"):
        try:
            parsed = urlparse(link)
            query = parse_qs(parsed.query)
            return {
                "protocol": "vless",
                "host": parsed.hostname,
                "port": parsed.port,
                "id": parsed.username,
                "security": query.get("security", ["none"])[0],
                "type": query.get("type", ["tcp"])[0],
                "name": parsed.fragment or "",
            }
        except Exception as e:
            raise ValueError(f"Failed to parse vless link: {e}")

    raise ValueError(f"Unsupported or invalid Xray link protocol: {link[:10]}...")


def _generate_wg_keys() -> Tuple[str, str]:
    """Generates a WireGuard private and public key pair using the wg utility."""
    try:
        priv_key = subprocess.check_output(["wg", "genkey"], text=True).strip()
        pub_key = subprocess.check_output(
            ["wg", "pubkey"], input=priv_key, text=True
        ).strip()
        return priv_key, pub_key
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Failed to generate WireGuard keys: 'wg' utility returned error. {e}"
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Failed to generate WireGuard keys: 'wg' utility not found on the system."
        )
    except Exception as e:
        raise RuntimeError(f"Unexpected error generating WireGuard keys: {e}")


def register_warp() -> Dict[str, Any]:
    """Registers a new Warp account with Cloudflare and returns the configuration."""
    log.debug("Starting WARP registration", hypothesisId="WARP")
    private_key, public_key = _generate_wg_keys()

    url = "https://api.cloudflareclient.com/v0a1922/reg"
    headers = {
        "User-Agent": "okhttp/3.12.1",
        "CF-Client-Version": "a-6.3-1922",
        "Content-Type": "application/json",
    }

    payload = {
        "key": public_key,
        "install_id": "",
        "warp_enabled": True,
        "tos": time.strftime("%Y-%m-%dT%H:%M:%S.000+00:00", time.gmtime()),
        "type": "Android",
        "locale": "en_US",
    }

    response = requests.post(url, headers=headers, json=payload, timeout=10)
    if response.status_code != 200:
        log.debug(
            "WARP registration failed",
            hypothesisId="WARP",
            status=response.status_code,
            body=response.text[:200],
        )
        # If registration fails, we MUST NOT return dummy values that cause Monit restart loops
        raise RuntimeError(
            f"Cloudflare WARP registration failed with status {response.status_code}: {response.text}"
        )

    data = response.json()
    # Cloudflare returns 'config' object with 'interface' and 'peers'
    interface = data.get("config", {}).get("interface", {})
    v4_addr = interface.get("addresses", {}).get("v4")
    v6_addr = interface.get("addresses", {}).get("v6")

    if not v4_addr and not v6_addr:
        raise RuntimeError("Cloudflare WARP registration returned no IP addresses.")

    # Return as a list of strings
    addresses = []
    if v4_addr:
        addresses.append(v4_addr)
    if v6_addr:
        addresses.append(v6_addr)

    # The peer public key is usually constant for WARP
    peer_pubkey = (
        data.get("config", {})
        .get("peers", [{}])[0]
        .get("public_key", "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=")
    )

    log.debug(
        "WARP registration successful", hypothesisId="WARP", v4=v4_addr, v6=v6_addr
    )

    return {"addresses": addresses, "privatekey": private_key, "pubkey": peer_pubkey}


def generate_vmess_link(config: Dict[str, Any]) -> str:
    """Generates a vmess:// link from a configuration dictionary."""
    json_data = json.dumps(config).encode("utf-8")
    return "vmess://" + base64.b64encode(json_data).decode("utf-8")
