import os
import unicodedata
import requests


def convert_to_ascii(text):
    return ''.join(c if ord(c) < 128 else unicodedata.normalize('NFKD', c).encode('ascii', 'ignore').decode('ascii') for c in text)


def get_public_ip(extra=False):
    try:
        ipinfo_token = os.environ.get('IPINFO_API_TOKEN')
        qp = ""
        if ipinfo_token:
            qp = f"token={ipinfo_token}"
        # Using a free public IP address API
        response = requests.get(f'https://ipinfo.io/json?{qp}')
        print("ipinfo/json: " + response.text)
        data = response.json()
        public_ip = data['ip']
        if extra:
            region = data.get('region', 'Unknown')
            country = data.get('country', 'Unknown')
            return {
                "ip": public_ip,
                "region": region,
                "country": country
            }
        else:
            return public_ip
    except requests.RequestException as e:
        print("Error: Unable to retrieve public IP address:", e, flush=True)
        print("Trying ip-api.com", flush=True)
        # fallback to ip-api.com
        r = requests.get("http://ip-api.com/json")
        data = r.json()
        print(f"ip-api.com/json: {data}")
        public_ip = data['query']
        if extra:
            region = data.get('regionName', 'Unknown')
            country = data.get('countryCode', 'Unknown')
            return {
                "ip": public_ip,
                "region": region,
                "country": country
            }
        else:
            return public_ip