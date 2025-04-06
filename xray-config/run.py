import json
import os
import threading
import time
import config
from utils import get_public_ip, csv_to_dict, exec, get_machine_id, parse_config_link
from flask import Flask, abort

valid_configs = {}
latest_metrics = ""

instance_location_info = get_public_ip(extra=True)

# Create a Flask application
app = Flask(__name__)

def update_metrics(configs):
    global latest_metrics

    instance_ip = instance_location_info['ip']
    instance_region = instance_location_info['region']
    instance_country = instance_location_info['country']

    metrics = []
    total_count = len(configs.values())
    failed_count = 0
    for config_link, value in configs.items():
        config_info = parse_config_link(config_link)
        labels = [
            f'config_link="{config_link}"',
            f'machine_id="{get_machine_id()}"',
            f'ip="{instance_ip}"',
            f'country="{instance_country}"',
            f'region="{instance_region}"',
            f'config_protocol="{config_info["protocol"]}"',
            f'config_host="{config_info["host"]}"',
            f'config_port="{config_info["port"]}"',
            f'config_security="{config_info["security"]}"',
            f'config_type="{config_info["type"]}"'
        ]
        inline_labels = ','.join(labels)
        t = f'vpn_config{{{inline_labels}}}'
        if value[0] == "passed":
            t += f" {value[4]}"  # delay
        else:
            failed_count += 1
            t += " -1"  # invalid delay
        metrics.append(t)

    latest_metrics = "# HELP vpn_config vpn config up(working) or down(not working).\n" \
              "# TYPE vpn_config gauge\n" + '\n'.join(metrics) + "\n"

    if failed_count == total_count:
        # all failed
        return False
    return True

def background_job():
    global valid_configs

    print("start bg job", flush=True)
    config_links = config.get_config_links()
    with open("configs.csv", "w") as configs_csv:
        configs_csv.write("\n".join(config_links))

    exec(["cat", "configs.csv"])

    print("waiting for 5 seconds", flush=True)
    time.sleep(5)
    """A function to run as a background job."""
    while True:
        if not config.initialized:
            time.sleep(5)
            continue
        print("start xray testing...", flush=True)
        exec(["xray-knife", "net", "http", "--thread", "1", "-d", "30000", "-r",
              "-e", "-p", "-a", "1000", "-f", "configs.csv", "--type", "csv"])
        # exec(["cat", "valid.csv"])
        valid_configs = csv_to_dict("valid.csv")

        success = update_metrics(valid_configs)

        print(f"xray test done - success: {success}", flush=True)

        if success:
            # run xray test every 5 minutes
            time.sleep(300)
        else:
            time.sleep(15)  # try again in 15 seconds

def cert_management_job():
    while True:
        if not config.initialized:
            time.sleep(5)
            continue
        else:
            if config.cf_api_token:
                time.sleep(86400 * 30)  # every month
                # try to renew the cert
                os.system(f'CF_Token={config.cf_api_token} .acme.sh/acme.sh --renew --dns dns_cf -d {config.direct_subdomain}')

# Start the background job in a separate thread
thread = threading.Thread(target=background_job)
thread.daemon = True
thread.start()

cert_thread = threading.Thread(target=cert_management_job)
cert_thread.daemon = True
cert_thread.start()

# Define a route for the root URL
@app.route('/config')
def get_xray_config():
    return json.dumps(config.xray_config, indent=4)

@app.route('/valid-configs')
def valid_configs_route():
    return json.dumps(valid_configs, indent=4)

@app.route('/subdomain')
def export_certs():
    return config.direct_subdomain

@app.route('/warps')
def get_warps():
    if not config.warps_ready:
        abort(404)
    return json.dumps(config.warps, indent=4)

@app.route('/metrics')
def metrics():
    return latest_metrics

# Run the application if executed directly
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
