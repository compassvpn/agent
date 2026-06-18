import ipaddress
import requests
from typing import Dict, Union

from shared_lib.logger import log


def get_public_ip(extra: bool = False) -> Union[str, Dict[str, str]]:
    """Fetches the public IP and optionally country info from multiple providers."""
    # HTTPS-only: the IP/country result is interpolated into generated configs
    # and metric labels, so it must not be fetched over a plaintext channel an
    # on-path attacker could poison. ip-api.com's free endpoint is HTTP-only and
    # was removed for this reason.
    providers = [
        {"url": "https://ipinfo.io/json", "ip_key": "ip", "country_key": "country"},
        {
            "url": "https://reallyfreegeoip.org/json/",
            "ip_key": "ip",
            "country_key": "country_name",
        },
        {
            "url": "https://api.ipify.org?format=json",
            "ip_key": "ip",
            "country_key": "country",
        },
    ]

    for provider in providers:
        # Defence-in-depth: never fall back to a plaintext endpoint.
        if not provider["url"].startswith("https://"):
            continue
        try:
            response = requests.get(provider["url"], timeout=5)
            if response.status_code == 200:
                data = response.json()
                ip = data.get(provider["ip_key"])
                if not ip:
                    continue

                # Validate the value is actually an IP before trusting it. The
                # result is interpolated into generated configs (Alloy River)
                # and Prometheus metric labels, so a non-IP string from a
                # compromised or MITM'd provider (the first provider is
                # plaintext HTTP) must never be accepted.
                try:
                    ip = str(ipaddress.ip_address(ip))
                except (ValueError, TypeError):
                    log.debug(
                        "Provider returned a non-IP value; skipping",
                        hypothesisId="NET",
                        provider=provider["url"],
                    )
                    continue

                log.debug(
                    "Public IP retrieved",
                    hypothesisId="NET",
                    provider=provider["url"],
                    ip=ip,
                )

                if extra:
                    return {
                        "ip": ip,
                        "country": data.get(provider["country_key"], "Unknown"),
                    }
                return ip
        except Exception as e:
            log.debug(
                "Provider failed",
                hypothesisId="NET",
                provider=provider["url"],
                error=str(e),
            )
            continue

    log.debug("All IP providers failed", hypothesisId="NET")
    if extra:
        return {"ip": "Unknown", "country": "Unknown"}
    return "Unknown"
