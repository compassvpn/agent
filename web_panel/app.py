import os
import subprocess
import signal
import io
import json
from typing import Dict, List, Any, Union
from flask import Flask, render_template, request, redirect, url_for, flash, Response

app = Flask(__name__)
app.secret_key = os.urandom(24) # Generate a secure, random key on each run
app.jinja_env.add_extension('jinja2.ext.do') # Enable the 'do' extension for template logic

# --- Custom Jinja Filter for Labels ---
ABBREVIATIONS = {'CF', 'ID', 'URL', 'API', 'IP', 'DNS', 'TCP', 'TLS', 'QUIC', 'SSL', 'WARP'}

def format_label(key_string: str) -> str:
    parts = key_string.split('_')
    formatted_parts = []
    for part in parts:
        if part.upper() in ABBREVIATIONS:
            formatted_parts.append(part.upper())
        else:
            formatted_parts.append(part.capitalize()) # Capitalize normal words
    return ' '.join(formatted_parts)

# Register the custom filter
app.jinja_env.filters['format_label'] = format_label
# --- End Custom Filter ---

ENV_PATH = '../env_file' # Path to the main configuration file (in PARENT dir, relative to app.py)
INBOUNDS_JSON_PATH = '../xray-config/inbounds.json' # Path to inbounds definition
BOOTSTRAP_SCRIPT = '../bootstrap.sh' # Script to run after saving config (in PARENT dir)
RESTART_SCRIPT = '../restart.sh' # Restart script in PARENT dir

# Load inbounds data and separate into Direct/CDN lists
direct_options = []
cdn_options = []
xray_inbounds_default = [] # Still needed for schema default

try:
    with open(INBOUNDS_JSON_PATH, 'r', encoding='utf-8') as f:
        inbounds_data = json.load(f)
    for ib in inbounds_data:
        option_dict = {'name': ib['name'], 'label': ib['name']} # Use name as label for simplicity in grouped view
        if ib.get('cloudflare', False):
            cdn_options.append(option_dict)
        else:
            direct_options.append(option_dict)
            xray_inbounds_default.append(ib['name']) # Default to selecting direct ones

except Exception as e:
    print(f"Error loading or processing {INBOUNDS_JSON_PATH}: {e}")
    # Provide basic fallback if file fails to load
    direct_options = [{'name': n, 'label': n} for n in ["vless-tcp-tls-direct", "vless-hu-tls-direct", "vless-xhttp-quic-direct"]]
    cdn_options = [{'name': n, 'label': n} for n in ["vless-hu-tls-cdn", "vless-xhttp-quic-cdn"]]
    xray_inbounds_default = ["vless-tcp-tls-direct", "vless-hu-tls-direct", "vless-xhttp-quic-direct"]

# Defines the structure, types, defaults, and help text for all configuration fields.
# This drives the web UI generation and saving logic.
CONFIG_SCHEMA: List[Dict[str, Any]] = [
    {
        'name': 'METRIC_PUSH_METHOD',
        'type': 'select',
        'default': 'grafana_agent',
        'options': ['grafana_agent', 'pushgateway'],
        'comment': 'Metric push method. Recommended: Grafana Agent. <a href="https://www.compassvpn.org/installation/configuration/#metric_push_method" target="_blank" rel="noopener noreferrer">Read More.</a>',
        'condition': None
    },
    {
        'name': 'GRAFANA_AGENT_REMOTE_WRITE_URL',
        'type': 'text',
        'default': '',
        'placeholder': 'https://prometheus-prod-XXX-grafana.grafana.net/api/prom/push',
        'comment': 'Endpoint URL for Grafana metrics. <a href="https://www.compassvpn.org/installation/configuration/#grafana_agent_remote_write_url" target="_blank" rel="noopener noreferrer">Read More.</a>',
        'condition': {'field': 'METRIC_PUSH_METHOD', 'value': 'grafana_agent'}
    },
    {
        'name': 'GRAFANA_AGENT_REMOTE_WRITE_USER',
        'type': 'text',
        'default': '',
        'placeholder': 'Your Grafana User ID',
        'comment': 'Username for Grafana metrics endpoint. <a href="https://www.compassvpn.org/installation/configuration/#grafana_agent_remote_write_user" target="_blank" rel="noopener noreferrer">Read More.</a>',
        'condition': {'field': 'METRIC_PUSH_METHOD', 'value': 'grafana_agent'}
    },
    {
        'name': 'GRAFANA_AGENT_REMOTE_WRITE_PASSWORD',
        'type': 'password',
        'default': '',
        'placeholder': 'Your Grafana API Key (glc_...)',
        'comment': 'Password Key for Grafana metrics endpoint. <a href="https://www.compassvpn.org/installation/configuration/#grafana_agent_remote_write_password" target="_blank" rel="noopener noreferrer">Read More.</a>',
        'condition': {'field': 'METRIC_PUSH_METHOD', 'value': 'grafana_agent'}
    },
    {
        'name': 'PUSHGATEWAY_URL',
        'type': 'text',
        'default': '',
        'placeholder': 'https://your-pushgateway-url:9091',
        'comment': 'URL of the Pushgateway server. <a href="https://www.compassvpn.org/installation/configuration/#pushgateway_url" target="_blank" rel="noopener noreferrer">Read More.</a>',
        'condition': {'field': 'METRIC_PUSH_METHOD', 'value': 'pushgateway'}
    },
    {
        'name': 'PUSHGATEWAY_AUTH_USER',
        'type': 'text',
        'default': '',
        'placeholder': 'Pushgateway Username',
        'comment': 'Username for Pushgateway authentication. <a href="https://www.compassvpn.org/installation/configuration/#pushgateway_auth_user" target="_blank" rel="noopener noreferrer">Read More.</a>',
        'condition': {'field': 'METRIC_PUSH_METHOD', 'value': 'pushgateway'}
    },
    {
        'name': 'PUSHGATEWAY_AUTH_PASSWORD',
        'type': 'password',
        'default': '',
        'placeholder': 'Pushgateway Password',
        'comment': 'Password for Pushgateway authentication. <a href="https://www.compassvpn.org/installation/configuration/#pushgateway_auth_password" target="_blank" rel="noopener noreferrer">Read More.</a>',
        'condition': {'field': 'METRIC_PUSH_METHOD', 'value': 'pushgateway'}
    },
    {
        'name': 'DONOR',
        'type': 'text',
        'default': '',
        'placeholder': 'e.g., my-server-01',
        'comment': 'Identifier for this server instance in metrics. <a href="https://www.compassvpn.org/installation/configuration/#donor" target="_blank" rel="noopener noreferrer">Read More.</a>'
    },
    {
        'name': 'REDEPLOY_INTERVAL',
        'type': 'select',
        'default': '1m',
        'options': ['1h', '4h', '1d', '7d', '14d', '1m', '3m'],
        'comment': 'How often configurations are reset (e.g., 7d for weekly). <a href="https://www.compassvpn.org/installation/configuration/#redeploy_interval" target="_blank" rel="noopener noreferrer">Read More.</a>'
    },
    {
        'name': 'IPINFO_API_TOKEN',
        'type': 'password',
        'default': '',
        'placeholder': 'Your IPInfo.io API Token',
        'comment': 'Token for IPInfo geolocation service. <a href="https://www.compassvpn.org/installation/configuration/#ipinfo_api_token" target="_blank" rel="noopener noreferrer">Read More.</a>'
    },
    {
        'name': 'CF_API_TOKEN',
        'type': 'password',
        'label': 'Cloudflare API Token',
        'placeholder': 'Enter Cloudflare API Token',
        'required': False,
        'comment': 'API Token for Cloudflare access. Create with Zone.Zone:Read, Zone.DNS:Edit permissions. <a href="https://www.compassvpn.org/installation/configuration/#cf_api_token" target="_blank" rel="noopener noreferrer">Read More.</a>'
    },
    {
        'name': 'CF_ZONE_ID',
        'type': 'text',
        'label': 'Cloudflare Zone ID',
        'placeholder': 'Enter Cloudflare Zone ID',
        'required': False,
        'comment': 'Zone ID for your domain in Cloudflare. <a href="https://www.compassvpn.org/installation/configuration/#cf_zone_id" target="_blank" rel="noopener noreferrer">Read More.</a>'
    },
    {
        'name': 'CF_CLEAN_IP_DOMAIN',
        'type': 'text',
        'label': 'Cloudflare Clean IP Domain',
        'default': 'npmjs.com',
        'required': False,
        'comment': 'Domain to use for finding clean Cloudflare IPs. Default: npmjs.com. <a href="https://www.compassvpn.org/installation/configuration/#cf_clean_ip_domain" target="_blank" rel="noopener noreferrer">Read More.</a>'
    },
    {
        'name': 'XRAY_OUTBOUND',
        'type': 'select',
        'label': 'Xray Outbound',
        'options': ['direct', 'warp'],
        'default': 'direct',
        'comment': 'Default outbound connection for Xray (Direct or Warp). <a href="https://www.compassvpn.org/installation/configuration/#xray_outbound" target="_blank" rel="noopener noreferrer">Read More.</a>'
    },
    {
        'name': 'XRAY_INBOUNDS',
        'type': 'checkbox_group', # Conceptual type change for template
        'label': 'Enabled Xray Inbounds',
        # 'options' key removed - template uses direct_options/cdn_options
        'default': xray_inbounds_default, # Keep default based on direct names
        'comment': 'Select the inbound protocols you want to enable. <a href="https://www.compassvpn.org/installation/configuration/#xray_inbounds" target="_blank" rel="noopener noreferrer">Read More.</a>'
    },
    {
        'name': 'SSL_PROVIDER',
        'type': 'select',
        'default': 'letsencrypt',
        'options': ['letsencrypt', 'zerossl'],
        'comment': 'Certificate Authority for SSL certificates. <a href="https://www.compassvpn.org/installation/configuration/#ssl_provider" target="_blank" rel="noopener noreferrer">Read More.</a>'
    },
    {
        'name': 'AUTO_UPDATE',
        'type': 'toggle',
        'default': 'on',
        'on_value': 'on',
        'off_value': 'off',
        'comment': 'Enable automatic updates for the agent software. <a href="https://www.compassvpn.org/installation/configuration/#auto_update" target="_blank" rel="noopener noreferrer">Read More.</a>'
    },
    {
        'name': 'NGINX_PATH',
        'type': 'text',
        'default': 'compass',
        'placeholder': 'e.g., myvpnpath (no slashes)',
        'comment': 'Internal NGINX routing path for the VPN service. <a href="https://www.compassvpn.org/installation/configuration/#nginx_path" target="_blank" rel="noopener noreferrer">Read More.</a>',
    },
    {
        'name': 'NGINX_FAKE_WEBSITE',
        'type': 'text',
        'default': 'www.google.com',
        'placeholder': 'e.g., www.bing.com',
        'comment': 'Website to proxy for obfuscation (must NOT be behind major CDN). <a href="https://www.compassvpn.org/installation/configuration/#nginx_fake_website" target="_blank" rel="noopener noreferrer">Read More.</a>',
    },
    {
        'name': 'CUSTOM_DNS',
        'type': 'select_custom',
        'default': 'controld',
        'options': ['default', 'cf', 'controld'],
        'comment': 'DNS resolver for the server. Use preset or custom URL. <a href="https://www.compassvpn.org/installation/configuration/#custom_dns" target="_blank" rel="noopener noreferrer">Read More.</a>'
    },
    {
        'name': 'DEBUG',
        'type': 'toggle',
        'default': 'disable',
        'on_value': 'enable',
        'off_value': 'disable',
        'comment': 'Enable verbose logging for troubleshooting. <a href="https://www.compassvpn.org/installation/configuration/#debug" target="_blank" rel="noopener noreferrer">Read More.</a>'
    },
]

# Reads the current key-value pairs from the env_file.
def load_current_config(file_path: str) -> Dict[str, str]:
    env_vars: Dict[str, str] = {}
    if os.path.exists(file_path):
        try:
            with io.open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    stripped_line = line.strip()
                    if not stripped_line or stripped_line.startswith('#'):
                        continue
                    if '=' in stripped_line:
                        try:
                            key, value = stripped_line.split('=', 1)
                            key = key.strip()
                            value = value.strip()
                            if key:
                                env_vars[key] = value
                        except ValueError:
                            continue # Ignore malformed lines
        except Exception as e:
            print(f"Error loading {file_path}: {e}") # Log error
    return env_vars

# Writes the configuration data to the env_file, preserving order and adding comments from the schema.
def write_env_file(file_path: str, env_data: Dict[str, Any]) -> None:
    # First, load the original config to find non-schema variables
    original_config = load_current_config(file_path)

    lines_to_write: List[str] = []
    schema_keys = {item['name'] for item in CONFIG_SCHEMA}
    all_keys_in_schema_order = [item['name'] for item in CONFIG_SCHEMA]

    # Write schema-defined variables first
    for key in all_keys_in_schema_order:
        schema_item = next((item for item in CONFIG_SCHEMA if item['name'] == key), None)
        if not schema_item: continue

        value = env_data.get(key, schema_item.get('default', ''))

        if isinstance(value, list):
            value = ','.join(value)

        value_str = str(value).strip().replace('\n', ' ').replace('\r', '')
        lines_to_write.append(f"{key}={value_str}\n\n")
    # Append non-schema variables from the original file
    header_added = False
    for key, value in original_config.items():
        if key not in schema_keys:
            if not header_added:
                lines_to_write.append("\n")
                header_added = True
            lines_to_write.append(f"{key}={value}\n\n")

    try:
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            f.writelines(lines_to_write)
    except Exception as e:
        print(f"Error writing {file_path}: {e}")
        flash(f'Error writing configuration file: {e}', 'danger')

# Sends a signal to shut down the Flask development server.
def shutdown_server() -> None:
    # Send SIGINT (Ctrl+C) to the current process
    os.kill(os.getpid(), signal.SIGINT)

# Defines the UI groups for organizing fields in the web panel.
UI_GROUPS: Dict[str, List[str]] = {
    "Metrics Configuration": [
        'METRIC_PUSH_METHOD', 'GRAFANA_AGENT_REMOTE_WRITE_URL', 'GRAFANA_AGENT_REMOTE_WRITE_USER', 'GRAFANA_AGENT_REMOTE_WRITE_PASSWORD',
        'PUSHGATEWAY_URL', 'PUSHGATEWAY_AUTH_USER', 'PUSHGATEWAY_AUTH_PASSWORD'
    ],
    "General Settings": [
        'DONOR', 'REDEPLOY_INTERVAL', 'IPINFO_API_TOKEN', 'AUTO_UPDATE'
    ],
    "Core Settings": [
        'XRAY_INBOUNDS', 'XRAY_OUTBOUND', 
        'NGINX_FAKE_WEBSITE', 'NGINX_PATH'
    ],
    "Cloudflare Integration": [
        'CF_API_TOKEN', 'CF_ZONE_ID',
        'CF_CLEAN_IP_DOMAIN'
    ],
    "System & Other Settings": [
        'CUSTOM_DNS', 'SSL_PROVIDER', 'DEBUG'
    ]
}

# Main route for displaying the form (GET) and handling submissions (POST).
@app.route('/', methods=['GET', 'POST'])
def index() -> Union[str, Response]:
    # Load existing config from env_file
    current_config = load_current_config(ENV_PATH)

    # Prepare data for the template: Use loaded values or fall back to schema defaults
    config_data = {}
    for item in CONFIG_SCHEMA:
        key = item['name']
        config_data[key] = current_config.get(key, item.get('default', ''))
        # Adjust handling for checkbox_group default loading
        if item['type'] == 'checkbox_group' and key not in current_config:
             config_data[key] = item.get('default', [])
        # Adjust ensure checkbox_group values are lists for template logic
        if item['type'] == 'checkbox_group' and key in current_config and isinstance(current_config[key], str):
             config_data[key] = current_config[key].split(',')

    # Handle form submission
    if request.method == 'POST':
        submitted_data = request.form.to_dict(flat=False)
        action = submitted_data.pop('action', [None])[0]
        env_to_save = current_config.copy()

        for key, values in submitted_data.items():
            if not values: continue
            schema_item = next((item for item in CONFIG_SCHEMA if item['name'] == key), None)
            if not schema_item: continue
            # Adjust saving logic for checkbox_group
            if schema_item['type'] == 'checkbox_group':
                 # Join selected values into comma-separated string
                 env_to_save[key] = ','.join(values)
            elif key == 'CUSTOM_DNS' and values[0] == 'custom':
                custom_text = request.form.get('CUSTOM_DNS_TEXT', '').strip()
                env_to_save[key] = custom_text if custom_text else next((item['default'] for item in CONFIG_SCHEMA if item['name'] == key), 'custom')
            elif key in ['CUSTOM_DNS_TEXT', 'REDEPLOY_INTERVAL_custom']: # Skip helper fields
                 continue
            else:
                 env_to_save[key] = values[0]

        write_env_file(ENV_PATH, env_to_save)

        # Check which action to perform after saving
        if action == 'save_close':
            flash(f'{os.path.basename(ENV_PATH)} saved successfully!', 'success')
            shutdown_server()
            # Return a simple styled message
            return '''
                <div style="padding: 20px; font-family: sans-serif; background-color: rgb(139, 92, 246, 0.5); border-radius: 10px;">
                    <h3>Configuration Saved.</h3>
                    <p>Panel is closed. To reopen, run <strong>./start_panel.sh</strong> in the server terminal.</p>
                </div>
            '''
        elif action == 'save_close_bootstrap':
            flash(f'{os.path.basename(ENV_PATH)} saved successfully!', 'success')

            # Check IDENTIFIER to determine which script should run
            newly_saved_config = load_current_config(ENV_PATH)
            identifier_value = newly_saved_config.get('IDENTIFIER', '').strip()

            script_to_run = '' # Use the constant name here
            script_message = ''
            if identifier_value:
                script_to_run = RESTART_SCRIPT # Use constant e.g., '../restart.sh'
                script_message = f'Restarting services using {os.path.basename(RESTART_SCRIPT)}...'
                print(f"Found IDENTIFIER, running script: {script_to_run}")
            else:
                script_to_run = BOOTSTRAP_SCRIPT # Use constant e.g., '../bootstrap.sh'
                script_message = f'IDENTIFIER not found/empty. Running initial bootstrap using {os.path.basename(BOOTSTRAP_SCRIPT)}...'
                print(f"IDENTIFIER not found/empty, running script: {script_to_run}")

            # Construct full path relative to the app.py file
            full_script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), script_to_run))
            script_basename = os.path.basename(full_script_path) # Get the actual script name

            if os.path.exists(full_script_path):
                try:
                    print(f"Attempting to run script: {full_script_path}")
                    # Ensure script is executable (best effort)
                    try:
                        os.chmod(full_script_path, 0o755)
                    except Exception as chmod_err:
                        print(f"Warning: Could not chmod script {full_script_path}: {chmod_err}")

                    # Run the script, detached, output redirected
                    script_dir = os.path.dirname(full_script_path)
                    print(f"Running subprocess in directory: {script_dir}")
                    # Use subprocess.run to wait and show output in terminal
                    subprocess.run(
                        [full_script_path],
                        cwd=script_dir,
                        check=False # Don't raise exception if script fails, just print output
                    )
                    flash(f'Successfully initiated: {script_basename}', 'info')
                    script_message = f'Successfully initiated <strong>{script_basename}</strong>.'
                except Exception as e:
                    print(f"Error running script {full_script_path}: {e}")
                    flash(f'Error trying to run {script_basename}: {e}', 'danger')
                    script_message = f'Error trying to run <strong>{script_basename}</strong>: {e}'
            else:
                error_msg = f"Script not found: {full_script_path}"
                print(error_msg)
                flash(error_msg, 'danger')
                script_message = error_msg

            shutdown_server()
            # Return generic message, start_panel.sh will handle execution
            return f'''
                <div style="padding: 20px; font-family: sans-serif; background-color: rgb(139, 92, 246, 0.5); border-radius: 10px;">
                    <h3>Configuration Saved.</h3>
                    <p>{script_message}</p>
                    <p>Panel is closed. To reopen, run <strong>./start_panel.sh</strong> in the server terminal.</p>
                 </div>
            '''

        # Default action: just save and reload the page
        flash(f'{os.path.basename(ENV_PATH)} saved successfully!', 'success')
        return redirect(url_for('index'))

    # Prepare UI groups for rendering, RESPECTING UI_GROUPS ORDER
    grouped_schema = {group: [] for group in UI_GROUPS} # Initialize with keys from UI_GROUPS
    schema_dict = {item['name']: item for item in CONFIG_SCHEMA} # Faster lookup

    # Iterate through UI_GROUPS to control order
    for group_title, keys_in_order in UI_GROUPS.items():
        for key in keys_in_order:
            if key in schema_dict:
                grouped_schema[group_title].append(schema_dict[key])
            else:
                 print(f"Warning: Key '{key}' in UI_GROUPS['{group_title}'] not found in CONFIG_SCHEMA.")

    # Pass the correctly ordered grouped_schema as ui_groups to the template
    return render_template('index.html', schema=CONFIG_SCHEMA, config_data=config_data, ui_groups=grouped_schema,
                           direct_options=direct_options, cdn_options=cdn_options)

# Script entry point: Set up directories and run the Flask app.
if __name__ == '__main__':
    # Ensure the necessary directories exist
    os.makedirs('web_panel/templates', exist_ok=True)
    os.makedirs('web_panel/static', exist_ok=True)

    # Create a dummy index.html if it doesn't exist, to prevent errors on first run
    if not os.path.exists('web_panel/templates/index.html'):
         with open('web_panel/templates/index.html', 'w') as f:
             f.write('<html><head><title>Config Panel</title></head><body><h1>Loading...</h1></body></html>')
    app.run(host='0.0.0.0', port=5050, debug=False)
