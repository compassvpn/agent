import base64
import csv
import json
import os
import urllib.parse
import subprocess
import sys
import requests


def exec(cmd):
    # Execute a command using subprocess.Popen
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # Capture stdout and stderr from the subprocess
    stdout, stderr = process.communicate()

    # Decode bytes to string (assuming UTF-8 encoding)
    stdout_str = stdout.decode('utf-8')
    stderr_str = stderr.decode('utf-8')

    # Print captured output to the main program's stdout and stderr
    print(f"{cmd} - stdout:")
    sys.stdout.write(stdout_str)

    print(f"{cmd} - stderr:")
    sys.stderr.write(stderr_str)


def get_machine_id():
    machine_id_path = '/host/etc/machine-id'  # Path to the machine-id file on the host
    try:
        with open(machine_id_path, 'r') as f:
            machine_id = f.read().strip()  # Read and strip any surrounding whitespace
            return machine_id
    except FileNotFoundError:
        print(f"Error: {machine_id_path} not found. Check if the file path is correct.")
        return None
    except Exception as e:
        print(f"Error reading {machine_id_path}: {e}")
        return None


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


def get_identifier():
    return os.environ['IDENTIFIER'].lower()


def csv_to_dict(file_path):
    result_dict = {}

    with open(file_path, 'r', newline='') as csvfile:
        csv_reader = csv.reader(csvfile)
        header_skipped = False
        for row in csv_reader:
            if not header_skipped:
                header_skipped = True
                continue  # Skip the header row
            if row:  # Check if the row is not empty
                key = row[0]  # Use the first column as the key
                values = row[1:]  # Use the remaining columns as values
                result_dict[key] = values

    return result_dict


def parse_config_link(link):
    protocol, url_without_protocol = link.split("://")

    if protocol == "vmess":
        payload = json.loads(base64.b64decode(url_without_protocol).decode())
        user, port, host, security, config_type = payload["id"], payload["port"], payload["add"], payload["tls"], payload["net"]
    else:
        # Split the URL into user_info, host_port, and query
        user_info, host_port_query = url_without_protocol.split('@', 1)

        # Split host_port_query into host_port and query
        host_port, query_string = host_port_query.split('?', 1)

        # Extract parameters from the query string
        query_params = urllib.parse.parse_qs(query_string.split("#")[0])

        # Extract individual parameters
        user = user_info
        host = host_port.split(':')[0]
        port = int(host_port.split(':')[1])
        security = query_params.get('security', [''])[0]
        config_type = query_params.get('type', [''])[0]

    return {
        'protocol': protocol,
        'user': user,
        'host': host,
        'port': port,
        'security': security,
        'type': config_type
    }


def register_warp():
    private_key = os.popen("wg genkey").read().strip()
    public_key = os.popen(f"echo \"{private_key}\" | wg pubkey").read().strip()
    url = "https://api.cloudflareclient.com/v0a737/reg"
    data = {
        "key": public_key,
        "warp_enabled": True,
        "tos": "2019-09-26T00:00:00.000+01:00",
        "type": "Android",
        "locale": "en_US"
    }
    
    # Make the POST request
    response = requests.post(url, json=data)

    print(data)
    print(response.content)
    
    # Check if the request was successful
    if response.status_code == 200:
        r = response.json()
        return {
            "pubkey": r['config']['peers'][0]['public_key'],
            "privatekey": private_key,
            "addresses": [r['config']['interface']['addresses']['v4']+"/32", r['config']['interface']['addresses']['v6']+"/128"]
        }
    else:
        return None

