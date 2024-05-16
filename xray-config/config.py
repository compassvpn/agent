import os

import requests

from utils import get_identifier, get_public_ip, register_warp, find_warp_endpoint

config_id = get_identifier()

config_uuid = os.popen(f"xray uuid -i {config_id}").read().replace("\n", "").strip()

cf_only = os.environ.get('CF_ONLY', 'false') in ['True', 'true', 'yes']
cf_enable = os.environ.get('CF_ENABLE', 'false') in ['True', 'true', 'yes']
cf_api_token = os.environ.get('CF_API_TOKEN', None)
cf_zone_id = os.environ.get('CF_ZONE_ID', None)
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
            if os.environ.get('SSL_PROVIDER', 'letsencrypt'):
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


def get_config_links():
    configs = []
    cf_clean_ip_domain = os.environ.get('CF_CLIENT_IP_DOMAIN', 'npmjs.com')
    if subdomain:
        # vless grpc tls cf - 2096
        configs.append(f"vless://{config_id}@{cf_clean_ip_domain}:2096?type=grpc&serviceName=&authority=&security=tls&fp=safari&alpn=h2%2Chttp%2F1.1&sni={subdomain}#vless grpc cf")
        # vless trojan tls cf - 2083
        configs.append(f"trojan://{config_id}@{cf_clean_ip_domain}:2083?security=tls&type=ws&headerType=&path=&host={subdomain}&sni={subdomain}&fp=&alpn=#Trojan ws cf")

        if not cf_only:
            # reality tcp xtls discordapp.com - 8443
            configs.append(f"vless://{config_id}@{server_ip}:8443?security=reality&type=tcp&headerType=&flow=xtls-rprx-vision&path=&host=&sni=discordapp.com&fp=chrome&pbk=SbVKOEMjK0sIlbwg4akyBg5mL5KZwwB-ed4eEE7YnRc&sid=&spx=#VLESS Reality tcp")
            # vless quic - 2082
            configs.append(f"vless://{config_id}@{server_ip}:2082?type=quic&quicSecurity=aes-128-gcm&key={config_id}&headerType=srtp&security=none#vless quic")
            # vless direct tcp tls - 2053
            configs.append(f"vless://{config_id}@{direct_subdomain}:2053?type=tcp&security=tls&fp=&alpn=h2%2Chttp%2F1.1&sni={direct_subdomain}#vless tcp tls direct")
            # vless direct grpc tls - 2086
            configs.append(f"vless://{config_id}@{direct_subdomain}:2086?type=grpc&serviceName=&authority=&security=tls&fp=&alpn=h2%2Chttp%2F1.1#vless grpc tls")
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
    cf_inbounds = [
        {
            "tag": "Trojan Websocket TLS",
            "listen": "0.0.0.0",
            "port": 2083,
            "protocol": "trojan",
            "settings": {
                "clients": [
                    {
                        "password": config_id,
                        "email": config_id
                    }
                ]
            },
            "streamSettings": {
                "network": "ws",
                "security": "tls",
                "tlsSettings": {
                    "certificates": [
                        {
                            "certificate": [
                                "-----BEGIN CERTIFICATE-----",
                                "MIIBvTCCAWOgAwIBAgIRAIY9Lzn0T3VFedUnT9idYkEwCgYIKoZIzj0EAwIwJjER",
                                "MA8GA1UEChMIWHJheSBJbmMxETAPBgNVBAMTCFhyYXkgSW5jMB4XDTIzMDUyMTA4",
                                "NDUxMVoXDTMzMDMyOTA5NDUxMVowJjERMA8GA1UEChMIWHJheSBJbmMxETAPBgNV",
                                "BAMTCFhyYXkgSW5jMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEGAmB8CILK7Q1",
                                "FG47g5VXg/oX3EFQqlW8B0aZAftYpHGLm4hEYVA4MasoGSxRuborhGu3lDvlt0cZ",
                                "aQTLvO/IK6NyMHAwDgYDVR0PAQH/BAQDAgWgMBMGA1UdJQQMMAoGCCsGAQUFBwMB",
                                "MAwGA1UdEwEB/wQCMAAwOwYDVR0RBDQwMoILZ3N0YXRpYy5jb22CDSouZ3N0YXRp",
                                "Yy5jb22CFCoubWV0cmljLmdzdGF0aWMuY29tMAoGCCqGSM49BAMCA0gAMEUCIQC1",
                                "XMIz1XwJrcu3BSZQFlNteutyepHrIttrtsfdd05YsQIgAtCg53wGUSSOYGL8921d",
                                "KuUcpBWSPkvH6y3Ak+YsTMg=",
                                "-----END CERTIFICATE-----"
                            ],
                            "key": [
                                "-----BEGIN RSA PRIVATE KEY-----",
                                "MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQg7ptMDsNFiL7iB5N5",
                                "gemkQUHIWvgIet+GiY7x7qB13V6hRANCAAQYCYHwIgsrtDUUbjuDlVeD+hfcQVCq",
                                "VbwHRpkB+1ikcYubiERhUDgxqygZLFG5uiuEa7eUO+W3RxlpBMu878gr",
                                "-----END RSA PRIVATE KEY-----"
                            ]
                        }
                    ],
                    "minVersion": "1.2",
                    "cipherSuites": "TLS_ECDHE_ECDSA_WITH_CHACHA20_POLY1305_SHA256:TLS_ECDHE_RSA_WITH_CHACHA20_POLY1305_SHA256:TLS_ECDHE_ECDSA_WITH_AES_256_GCM_SHA384:TLS_ECDHE_RSA_WITH_AES_256_GCM_SHA384:TLS_ECDHE_ECDSA_WITH_AES_128_GCM_SHA256:TLS_ECDHE_RSA_WITH_AES_128_GCM_SHA256"
                }
            },
            "sniffing": {
                "enabled": False,
                "destOverride": [
                    "http",
                    "tls"
                ]
            }
        },  # 2083 - cf - trojan
        {
            "listen": "0.0.0.0",
            "port": 2096,
            "protocol": "vless",
            "settings": {
                "clients": [
                    {
                        "email": config_id,
                        "flow": "",
                        "id": config_uuid
                    }
                ],
                "decryption": "none",
                "fallbacks": []
            },
            "streamSettings": {
                "grpcSettings": {
                    "authority": "",
                    "multiMode": False,
                    "serviceName": ""
                },
                "network": "grpc",
                "security": "tls",
                "tlsSettings": {
                    "alpn": [
                        "h2",
                        "http/1.1"
                    ],
                    "certificates": [
                        {
                            "certificate": [
                                "-----BEGIN CERTIFICATE-----",
                                "MIIBvTCCAWOgAwIBAgIRAIY9Lzn0T3VFedUnT9idYkEwCgYIKoZIzj0EAwIwJjER",
                                "MA8GA1UEChMIWHJheSBJbmMxETAPBgNVBAMTCFhyYXkgSW5jMB4XDTIzMDUyMTA4",
                                "NDUxMVoXDTMzMDMyOTA5NDUxMVowJjERMA8GA1UEChMIWHJheSBJbmMxETAPBgNV",
                                "BAMTCFhyYXkgSW5jMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEGAmB8CILK7Q1",
                                "FG47g5VXg/oX3EFQqlW8B0aZAftYpHGLm4hEYVA4MasoGSxRuborhGu3lDvlt0cZ",
                                "aQTLvO/IK6NyMHAwDgYDVR0PAQH/BAQDAgWgMBMGA1UdJQQMMAoGCCsGAQUFBwMB",
                                "MAwGA1UdEwEB/wQCMAAwOwYDVR0RBDQwMoILZ3N0YXRpYy5jb22CDSouZ3N0YXRp",
                                "Yy5jb22CFCoubWV0cmljLmdzdGF0aWMuY29tMAoGCCqGSM49BAMCA0gAMEUCIQC1",
                                "XMIz1XwJrcu3BSZQFlNteutyepHrIttrtsfdd05YsQIgAtCg53wGUSSOYGL8921d",
                                "KuUcpBWSPkvH6y3Ak+YsTMg=",
                                "-----END CERTIFICATE-----"
                            ],
                            "key": [
                                "-----BEGIN RSA PRIVATE KEY-----",
                                "MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQg7ptMDsNFiL7iB5N5",
                                "gemkQUHIWvgIet+GiY7x7qB13V6hRANCAAQYCYHwIgsrtDUUbjuDlVeD+hfcQVCq",
                                "VbwHRpkB+1ikcYubiERhUDgxqygZLFG5uiuEa7eUO+W3RxlpBMu878gr",
                                "-----END RSA PRIVATE KEY-----"
                            ]
                        }
                    ],
                    "cipherSuites": "",
                    "maxVersion": "1.3",
                    "minVersion": "1.1",
                    "rejectUnknownSni": False,
                    "serverName": subdomain
                }
            },
            "tag": "inbound-2096",
            "sniffing": {
                "enabled": False,
                "destOverride": [
                    "http",
                    "tls",
                    "quic",
                    "fakedns"
                ]
            }
        }  # 2096 - cf - vless
    ]
    inbounds += cf_inbounds

if not cf_only:
    direct_inbounds = [
        {
            "listen": "0.0.0.0",
            "port": 2053,
            "protocol": "vless",
            "settings": {
                "clients": [
                    {
                        "email": config_id,
                        "flow": "",
                        "id": config_uuid
                    }
                ],
                "decryption": "none",
                "fallbacks": []
            },
            "streamSettings": {
                "network": "tcp",
                "security": "tls",
                "tcpSettings": {
                    "acceptProxyProtocol": False,
                    "header": {
                        "type": "none"
                    }
                },
                "tlsSettings": {
                    "alpn": [
                        "h2",
                        "http/1.1"
                    ],
                    "certificates": [
                        {
                            "certificate": [
                                cert_public
                            ],
                            "key": [
                                cert_private
                            ],
                            "ocspStapling": 3600
                        }
                    ],
                    "cipherSuites": "",
                    "maxVersion": "1.3",
                    "minVersion": "1.1",
                    "rejectUnknownSni": False,
                    "serverName": direct_subdomain
                }
            },
            "tag": "inbound-2053",
            "sniffing": {
                "enabled": False,
                "destOverride": [
                    "http",
                    "tls",
                    "quic",
                    "fakedns"
                ]
            }
        },  # 2053
        {
            "listen": "0.0.0.0",
            "port": 2086,
            "protocol": "vless",
            "settings": {
                "clients": [
                    {
                        "email": config_id,
                        "flow": "",
                        "id": config_uuid
                    }
                ],
                "decryption": "none",
                "fallbacks": []
            },
            "streamSettings": {
                "grpcSettings": {
                    "authority": "",
                    "multiMode": False,
                    "serviceName": ""
                },
                "network": "grpc",
                "security": "tls",
                "tlsSettings": {
                    "alpn": [
                        "h2",
                        "http/1.1"
                    ],
                    "certificates": [
                        {
                            "certificate": [
                                cert_public
                            ],
                            "key": [
                                cert_private
                            ],
                            "ocspStapling": 3600
                        }
                    ],
                    "cipherSuites": "",
                    "maxVersion": "1.3",
                    "minVersion": "1.1",
                    "rejectUnknownSni": False,
                    "serverName": ""
                }
            },
            "tag": "inbound-2086",
            "sniffing": {
                "enabled": False,
                "destOverride": [
                    "http",
                    "tls",
                    "quic",
                    "fakedns"
                ]
            }
        },  # 2086
        {
            "tag": "VLESS TCP REALITY",
            "listen": "0.0.0.0",
            "port": 8443,
            "protocol": "vless",
            "settings": {
                "clients": [
                    {
                        "email": config_id,
                        "flow": "xtls-rprx-vision",
                        "id": config_uuid
                    }
                ],
                "decryption": "none"
            },
            "streamSettings": {
                "network": "tcp",
                "tcpSettings": {},
                "security": "reality",
                "realitySettings": {
                    "show": False,
                    "dest": "discordapp.com:443",
                    "xver": 0,
                    "serverNames": [
                        "cdn.discordapp.com",
                        "discordapp.com"
                    ],
                    "privateKey": "MMX7m0Mj3faUstoEm5NBdegeXkHG6ZB78xzBv2n3ZUA",
                    "shortIds": [
                        "",
                        "6ba85179e30d4fc2"
                    ]
                }
            },
            "sniffing": {
                "enabled": False,
                "destOverride": [
                    "http",
                    "tls"
                ]
            }
        },  # 8443
        {
            "listen": None,
            "port": 2082,
            "protocol": "vless",
            "settings": {
                "clients": [
                    {
                        "email": config_id,
                        "flow": "",
                        "id": config_uuid
                    }
                ],
                "decryption": "none",
                "fallbacks": []
            },
            "streamSettings": {
                "network": "quic",
                "quicSettings": {
                    "header": {
                        "type": "srtp"
                    },
                    "key": config_id,
                    "security": "aes-128-gcm"
                },
                "security": "none"
            },
            "tag": "inbound-2082",
            "sniffing": {
                "enabled": False,
                "destOverride": [
                    "http",
                    "tls",
                    "quic",
                    "fakedns"
                ]
            }
        },  # 2082
    ]
    inbounds += direct_inbounds

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
