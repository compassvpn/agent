import base64
import json
import os
import string

import requests

from utils import get_identifier, get_public_ip, register_warp, find_warp_endpoint

config_id = get_identifier()

config_uuid = os.popen(f"xray uuid -i {config_id}").read().replace("\n", "").strip()

cf_only = os.environ.get('CF_ONLY', 'false') in ['True', 'true', 'yes']
cf_enable = os.environ.get('CF_ENABLE', 'false') in ['True', 'true', 'yes']
cf_api_token = os.environ.get('CF_API_TOKEN', None)
cf_zone_id = os.environ.get('CF_ZONE_ID', None)
xray_inbounds = os.environ.get("XRAY_INBOUNDS", "").split(",")

domain = None
subdomain = None
direct_subdomain = None
cert_public = ""
cert_private = ""
initialized = False

server_ip = get_public_ip()


def get_domain():
    global domain
    # Construct the API endpoint URL
    url = f'https://api.cloudflare.com/client/v4/zones/{cf_zone_id}'

    # Set the headers with your API token
    headers = {
        'Authorization': f'Bearer {cf_api_token}',
        'Content-Type': 'application/json',
    }

    # Send a GET request to the Cloudflare API
    response = requests.get(url, headers=headers)

    # Check if the request was successful (status code 200)
    if response.status_code == 200:
        # Extract the domain name from the response
        domain = response.json()['result']['name']
        print(f"The domain name associated with zone ID {cf_zone_id} is: {domain}")
    else:
        print(f"Failed to retrieve domain name. Status code: {response.status_code}")


def create_cf_records():
    def dns_record_already_exist(record_name):
        # Construct the API endpoint URL
        url = f'https://api.cloudflare.com/client/v4/zones/{cf_zone_id}/dns_records?type=A&name={record_name}.{domain}'

        # Set the headers with your API token
        headers = {
            'Authorization': f'Bearer {cf_api_token}',
            'Content-Type': 'application/json',
        }

        # Send a GET request to the Cloudflare API
        response = requests.get(url, headers=headers)

        # Check if the request was successful (status code 200)
        if response.status_code == 200:
            # Parse the response to see if the record exists
            dns_records = response.json()['result']
            if dns_records:
                print(f"The DNS record {record_name} already exists.")
                return True
            else:
                print(f"The DNS record {record_name} does not exist.")
                return False
        else:
            print(f"Failed to check DNS records. Status code: {response.status_code}")
            return None

    def create_dns_record(name, proxied):
        # API endpoint
        endpoint = f'https://api.cloudflare.com/client/v4/zones/{cf_zone_id}/dns_records'

        # DNS record details
        record_type = 'A'
        content = server_ip  # IP address or content of the record
        ttl = 1  # TTL in seconds

        if dns_record_already_exist(name):
            return name

        # API request payload
        data = {
            'type': record_type,
            'name': name,
            'content': content,
            'ttl': ttl,
            'proxied': proxied
        }

        # API request headers
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {cf_api_token}'
        }

        # Send POST request to create DNS record
        response = requests.post(endpoint, json=data, headers=headers)

        # Check response status
        if response.status_code == 200:
            print(f"DNS record {data} added successfully!")
            return name
        else:
            print(f"Failed to add DNS record. Status code: {response.status_code}, Error: {response.text}")
            return None

    name = get_identifier() + "-" + server_ip.replace(".", "")  # Name of the record
    if not cf_only:
        create_dns_record(name + "-direct", False)  # direct (no proxy)
    create_dns_record(name, True)  # direct (cf proxy)

    return name


if os.environ.get('CF_ENABLE', '') == 'true':
    get_domain()
    a_record = create_cf_records()
    if create_cf_records() is not None:
        subdomain = f"{a_record}.{domain}"

        if not cf_only:
            direct_subdomain = f"{a_record}-direct.{domain}"
            if os.environ.get('SSL_PROVIDER', 'letsencrypt') == "letsencrypt":
                ssl_provider_server = "--server letsencrypt"
            else:
                ssl_provider_server = "--server zerossl"
            # create certificates
            if os.path.exists(f"/root/.acme.sh/{direct_subdomain}_ecc/fullchain.cer"):
                print("certificate already exists!")
                # try to renew certs (if needed)
                cmd = f'CF_Token={cf_api_token} .acme.sh/acme.sh {ssl_provider_server} --renew --dns dns_cf -d {direct_subdomain}'
                os.system(cmd)
            else:
                os.system('.acme.sh/acme.sh --register-account -m my@example.com')
                cmd = f'CF_Token={cf_api_token} .acme.sh/acme.sh {ssl_provider_server} --issue --dns dns_cf -d {direct_subdomain}'
                print(cmd, flush=True)
                os.system(cmd)
                os.system("ls /root/.acme.sh/")
            with open(f"/root/.acme.sh/{direct_subdomain}_ecc/fullchain.cer", 'r') as file:
                cert_public = file.read()
            with open(f"/root/.acme.sh/{direct_subdomain}_ecc/{direct_subdomain}.key", 'r') as file:
                cert_private = file.read()

    initialized = True

cf_clean_ip_domain = os.environ.get('CF_CLIENT_IP_DOMAIN', 'npmjs.com')

with open("inbounds.json") as f:
    inbound_template = string.Template(f.read())
    all_inbounds = json.loads(inbound_template.substitute({"config_id": config_id,
                                                           "config_uuid": config_uuid,
                                                           "cf_clean_ip_domain": cf_clean_ip_domain,
                                                           "server_ip": server_ip,
                                                           "direct_subdomain": direct_subdomain,
                                                           "subdomain": subdomain,
                                                           "cert_public": cert_public,
                                                           "cert_private": cert_private}))
    configured_inbounds = [inbound for inbound in all_inbounds if inbound.get("name") in xray_inbounds]
    for inbound in configured_inbounds:
        if isinstance(inbound.get("link"), dict):
            inbound["link"] = "vmess://" + base64.b64encode(json.dumps(inbound["link"]).encode()).decode()


def get_config_links():
    configs = []
    if subdomain:
        configs.extend([inbound.get("link", "") for inbound in configured_inbounds if inbound.get("couldflare", False)])
        if not cf_only:
            configs.extend([inbound.get("link", "") for inbound in configured_inbounds if inbound.get("couldflare", False) is False])
    return configs

inbounds = [{
    "listen": "0.0.0.0",
    "port": 54321,
    "protocol": "dokodemo-door",
    "settings": {
        "address": "127.0.0.1"
    },
    "tag": "api"
}]
if cf_enable:
    inbounds.extend([inbound["inbound"] for inbound in configured_inbounds if inbound.get("couldflare", False)])

if not cf_only:
    inbounds.extend([inbound["inbound"] for inbound in configured_inbounds if inbound.get("couldflare", False) is False])

xray_config = {
    "log": {
        "access": "none",
        "loglevel": "warning",
        "dnsLog": False
    },
    "routing": {
        "domainStrategy": "IPIfNonMatch",
        "rules": [
            {
                "type": "field",
                "inboundTag": [
                    "api"
                ],
                "outboundTag": "api"
            },
            {
                "type": "field",
                "outboundTag": "blocked",
                "ip": [
                    "geoip:private",
                    "geoip:ru",
                    "ext:geoip_IR.dat:ir"
                ]
            },
            {
                "type": "field",
                "outboundTag": "blocked",
                "protocol": [
                    "bittorrent"
                ]
            },
            {
                "type": "field",
                "outboundTag": "blocked",
                "domain": [
                    "geosite:category-gov-ru",
                    "regexp:.*\\.ru$",
                    "regexp:.*\\.ir$",
                    "regexp:.*\\.xn--mgba3a4f16a$",
                    "ext:geosite_IR.dat:ir",
                    "geosite:category-ads-all",
                    "ext:geosite_IR.dat:category-ads-all"
                ]
            }
        ]
    },
    "dns": None,
    "inbounds": inbounds,
    "outbounds": [
        {
            "tag": "direct",
            "protocol": "freedom",
            "settings": {}
        },
        {
            "tag": "blocked",
            "protocol": "blackhole",
            "settings": {}
        }
    ],
    "transport": None,
    "policy": {
        "levels": {
            "0": {
                "statsUserDownlink": True,
                "statsUserUplink": True
            }
        },
        "system": {
            "statsInboundDownlink": True,
            "statsInboundUplink": True
        }
    },
    "api": {
        "tag": "api",
        "services": [
            "HandlerService",
            "LoggerService",
            "StatsService"
        ]
    },
    "stats": {},
    "reverse": None,
    "fakeDns": None
}

if os.environ.get('XRAY_OUTBOUND') == 'warp':
    warp = register_warp()
    endpoint = find_warp_endpoint()
    xray_config['outbounds'][0] = {
        "protocol": "wireguard",
        "settings": {
            "reserved": [0, 0, 0],
            "mtu": 1280,
            "kernelMode": False,
            "domainStrategy": "ForceIPv4",
            "secretKey": warp['privatekey'],
            "address": warp['addresses'],
            "peers": [
                {
                    "publicKey": warp['pubkey'],
                    "allowedIPs": [
                        "0.0.0.0/0",
                        "::/0"
                    ],
                    "endpoint": endpoint
                }
            ]
        },
        "tag": "direct"
    }
