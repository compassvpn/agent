import os
import subprocess
import signal
import io
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
BOOTSTRAP_SCRIPT = '../bootstrap.sh' # Script to run after saving config (in PARENT dir)
RESTART_SCRIPT = '../restart.sh' # Restart script in PARENT dir

# Defines the structure, types, defaults, and help text for all configuration fields.
# This drives the web UI generation and saving logic.
CONFIG_SCHEMA = [
    {
        'name': 'METRIC_PUSH_METHOD',
        'type': 'select',
        'default': 'grafana_agent',
        'options': ['grafana_agent', 'pushgateway'],
        'comment': 'Method for sending metrics. Grafana Agent (via Grafana Cloud) is simpler. Pushgateway requires a self-hosted Prometheus.'
    },
    {
        'name': 'GRAFANA_AGENT_REMOTE_WRITE_URL',
        'type': 'text',
        'default': '',
        'comment': 'Grafana Cloud Prometheus Remote Write URL (e.g., https://XXX). Obtain from your Grafana Cloud stack details.',
        'placeholder': 'e.g., https://prometheus-prod-us-XXX.grafana.net/api/prom/push',
        'condition': {'field': 'METRIC_PUSH_METHOD', 'value': 'grafana_agent'}
    },
    {
        'name': 'GRAFANA_AGENT_REMOTE_WRITE_USER',
        'type': 'text',
        'default': '',
        'comment': 'Grafana Cloud Prometheus Username (Stack User ID). Obtain from your Grafana Cloud stack details.',
        'placeholder': 'e.g., 123456',
        'condition': {'field': 'METRIC_PUSH_METHOD', 'value': 'grafana_agent'}
    },
    {
        'name': 'GRAFANA_AGENT_REMOTE_WRITE_PASSWORD',
        'type': 'password',
        'default': '',
        'comment': 'Grafana Cloud Prometheus Password (API Key). Generate from your Grafana Cloud stack details.',
        'placeholder': 'e.g., glc_XXX',
        'condition': {'field': 'METRIC_PUSH_METHOD', 'value': 'grafana_agent'}
    },
    {
        'name': 'PUSHGATEWAY_URL',
        'type': 'text',
        'default': '',
        'comment': 'URL of your self-hosted Pushgateway instance (e.g., http://your-pushgateway:9091).',
        'placeholder': 'e.g., http://192.168.1.100:9091',
        'condition': {'field': 'METRIC_PUSH_METHOD', 'value': 'pushgateway'}
    },
    {
        'name': 'PUSHGATEWAY_AUTH_USER',
        'type': 'text',
        'default': '',
        'comment': 'Optional: Username for Pushgateway basic authentication.',
        'placeholder': 'e.g., prom_user',
        'condition': {'field': 'METRIC_PUSH_METHOD', 'value': 'pushgateway'}
    },
    {
        'name': 'PUSHGATEWAY_AUTH_PASSWORD',
        'type': 'password',
        'default': '',
        'comment': 'Optional: Password for Pushgateway basic authentication.',
        'placeholder': 'Enter Pushgateway password',
        'condition': {'field': 'METRIC_PUSH_METHOD', 'value': 'pushgateway'}
    },
    {
        'name': 'DONOR',
        'type': 'text',
        'default': '',
        'comment': 'A unique name for this server instance, used as a label in metrics.',
        'placeholder': 'e.g., my-vps-1',
    },
    {
        'name': 'REDEPLOY_INTERVAL',
        'type': 'select',
        'default': '7d',
        'options': ['1h', '4h', '1d', '7d', '14d', '1m', '3m'],
        'comment': 'Frequency for resetting configurations (e.g., 1d=daily, 7d=weekly, 1m=monthly).'
    },
    {
        'name': 'IPINFO_API_TOKEN',
        'type': 'password',
        'default': '',
        'comment': 'API Token from <a href="https://ipinfo.io/" target="_blank">IPInfo.io</a> (free tier available) for geolocation features.',
        'placeholder': 'Enter IPInfo.io API Token',
    },
    {
        'name': 'CF_ENABLE',
        'type': 'toggle',
        'default': 'true',
        'on_value': 'true',
        'off_value': 'false',
        'comment': 'Enable Cloudflare CDN integration. Routes traffic via Cloudflare, useful for bypassing blocks.'
    },
    {
        'name': 'CF_ONLY',
        'type': 'toggle',
        'default': 'false',
        'on_value': 'true',
        'off_value': 'false',
        'comment': 'Force ALL traffic through Cloudflare. Use ONLY if direct server access is completely blocked.',
        'condition': {'field': 'CF_ENABLE', 'value': 'true'}
    },
    {
        'name': 'CF_API_TOKEN',
        'type': 'password',
        'default': '',
        'comment': 'Cloudflare API Token (Permissions: Zone-DNS-Edit, Zone-SSL/Certificates-Edit).',
        'placeholder': 'Enter Cloudflare API Token',
    },
    {
        'name': 'CF_ZONE_ID',
        'type': 'text',
        'default': '',
        'comment': 'Cloudflare Zone ID for your domain (find on domain overview page).',
        'placeholder': 'e.g., abc123def456ghi789...',
    },
    {
        'name': 'CF_CLEAN_IP_DOMAIN',
        'type': 'text',
        'default': '',
        'comment': 'A Cloudflare-proxied domain or direct Cloudflare IP (e.g., npmjs.com or 104.17.223.1 or speed.cloudflare.com).',
        'placeholder': 'e.g., npmjs.com or 104.17.223.1 or speed.cloudflare.com',
    },
    {
        'name': 'XRAY_OUTBOUND',
        'type': 'select',
        'default': 'direct',
        'options': ['direct', 'warp'],
        'comment': 'How server\'s outbound connections are routed. \'warp\' uses Cloudflare WARP (may bypass some restrictions).'
    },
    {
        'name': 'XRAY_INBOUNDS',
        'type': 'checkbox',
        'default': ['vless-tcp-tls-direct', 'vless-hu-tls-direct', 'vless-hu-tls-cdn', 'vless-xhttp-quic-direct', 'vless-xhttp-quic-cdn'],
        'options': ['vless-tcp-tls-direct', 'vless-hu-tls-direct', 'vless-hu-tls-cdn', 'vless-xhttp-quic-direct', 'vless-xhttp-quic-cdn'],
        'comment': 'Select the client connection methods to enable. \'cdn\' variants require CF_ENABLE=true.'
    },
    {
        'name': 'SSL_PROVIDER',
        'type': 'select',
        'default': 'letsencrypt',
        'options': ['letsencrypt', 'zerossl'],
        'comment': 'Certificate Authority for SSL certificates. Let\'s Encrypt is recommended.'
    },
    {
        'name': 'AUTO_UPDATE',
        'type': 'toggle',
        'default': 'on',
        'on_value': 'on',
        'off_value': 'off',
        'comment': 'Enable automatic updates for the agent software (recommended: on).'
    },
    {
        'name': 'NGINX_PATH',
        'type': 'text',
        'default': 'compass',
        'comment': 'Internal NGINX routing path for the VPN service (usually no need to change).',
        'placeholder': 'e.g., myvpnpath (no slashes)',
    },
    {
        'name': 'NGINX_FAKE_WEBSITE',
        'type': 'text',
        'default': 'www.google.com',
        'comment': 'Website to proxy for obfuscation (must NOT be behind Cloudflare/major CDN).',
        'placeholder': 'e.g., www.bing.com',
    },
    {
        'name': 'CUSTOM_DNS',
        'type': 'select_custom',
        'default': 'controld',
        'options': ['default', 'cf', 'controld'],
        'comment': 'DNS resolver for the server. ControlD offers filtering. Select preset or provide custom URL (e.g., tls+local://1.1.1.1).'
    },
    {
        'name': 'DEBUG',
        'type': 'toggle',
        'default': 'disable',
        'on_value': 'enable',
        'off_value': 'disable',
        'comment': 'Enable verbose logging for Xray-core and DNS. Use only for troubleshooting.'
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
    lines_to_write: List[str] = []
    schema_comments = {item['name']: item.get('comment', '') for item in CONFIG_SCHEMA}
    all_keys_in_schema_order = [item['name'] for item in CONFIG_SCHEMA]

    for key in all_keys_in_schema_order:
        schema_item = next((item for item in CONFIG_SCHEMA if item['name'] == key), None)
        if not schema_item: continue

        # Add comment from schema if it exists
        comment = schema_comments.get(key)
        if comment:
            lines_to_write.append(f"# {comment}\n")

        # Get value from submitted data or default
        value = env_data.get(key, schema_item.get('default', ''))

        # Handle list type (checkboxes)
        if isinstance(value, list):
            value = ','.join(value)

        # Ensure value is string, stripped, and contains no newlines
        value_str = str(value).strip().replace('\n', ' ').replace('\r', '')

        lines_to_write.append(f"{key}={value_str}\n")

        # Add a blank line after each variable for spacing (optional, but can improve readability)
        lines_to_write.append("\n")

    try:
        # Write using newline='' to prevent OS-specific newline translation
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            f.writelines(lines_to_write)
    except Exception as e:
        print(f"Error writing {file_path}: {e}") # Log error
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
        'XRAY_OUTBOUND', 'XRAY_INBOUNDS',
        'NGINX_PATH', 'NGINX_FAKE_WEBSITE'
    ],
    "Cloudflare Integration": [
        'CF_API_TOKEN', 'CF_ZONE_ID',
        'CF_ENABLE', 'CF_ONLY', 'CF_CLEAN_IP_DOMAIN'
    ],
    "System & Other Settings": [
        'SSL_PROVIDER', 'CUSTOM_DNS', 'DEBUG'
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
        if item['type'] == 'checkbox' and key not in current_config:
            config_data[key] = item.get('default', [])

    # Handle form submission
    if request.method == 'POST':
        submitted_data = request.form.to_dict(flat=False)
        action = submitted_data.pop('action', [None])[0]
        env_to_save = current_config.copy()

        for key, values in submitted_data.items():
            if not values: continue
            schema_item = next((item for item in CONFIG_SCHEMA if item['name'] == key), None)
            if not schema_item: continue
            if schema_item['type'] == 'checkbox':
                env_to_save[key] = values
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
                <div style="padding: 20px; font-family: sans-serif; background-color: #e9ecef; border-radius: 5px;">
                    <h4>Configuration Saved</h4>
                    <p>Panel is shutting down. To reopen, run <code>./start_panel.sh</code> in the server terminal.</p>
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

                    # Run the script, detached, but capture output temporarily for debugging
                    # Set working directory to the script's directory (parent of web_panel)
                    script_dir = os.path.dirname(full_script_path)
                    print(f"Running subprocess in directory: {script_dir}")
                    subprocess.Popen(
                        [full_script_path],
                        start_new_session=True,
                        cwd=script_dir  # Set working directory
                        # stdout=subprocess.DEVNULL, # Temporarily removed for debugging
                        # stderr=subprocess.DEVNULL  # Temporarily removed for debugging
                    )
                    flash(f'Successfully initiated: {script_basename}', 'info')
                    script_message = f'Successfully initiated background process: {script_basename}.'
                except Exception as e:
                    print(f"Error running script {full_script_path}: {e}")
                    flash(f'Error trying to run {script_basename}: {e}', 'danger')
                    script_message = f'Error trying to run {script_basename}: {e}'
            else:
                error_msg = f"Script not found: {full_script_path}"
                print(error_msg)
                flash(error_msg, 'danger')
                script_message = error_msg

            shutdown_server()
            # Return generic message, start_panel.sh will handle execution
            return f'''
                <div style="padding: 20px; font-family: sans-serif; background-color: #e9ecef; border-radius: 5px;">
                    <h4>Configuration Saved</h4>
                    <p>{script_message}</p>
                    <p>Panel is shutting down...</p>
                 </div>
            '''

        # Default action: just save and reload the page
        flash(f'{os.path.basename(ENV_PATH)} saved successfully!', 'success')
        return redirect(url_for('index'))

    # Prepare UI groups for rendering
    grouped_schema = {group: [] for group in UI_GROUPS}
    all_grouped_keys = set(key for group_keys in UI_GROUPS.values() for key in group_keys)

    # Add fields to their respective groups
    for item in CONFIG_SCHEMA:
        key = item['name']
        found_in_group = False
        for group, keys in UI_GROUPS.items():
            if key in keys:
                grouped_schema[group].append(item)
                found_in_group = True
                break
        # Optional: Handle ungrouped items if necessary
        # if not found_in_group:
        #    print(f"Warning: Field '{key}' not assigned to any UI group.")

    return render_template('index.html', schema=CONFIG_SCHEMA, config_data=config_data, ui_groups=grouped_schema)

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
