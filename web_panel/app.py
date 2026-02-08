import os
import signal
import json
from typing import Dict, List, Any
from flask import Flask, render_template, request, redirect, url_for, flash

from shared_lib.paths import ENV_FILE, INBOUNDS_JSON, BOOTSTRAP_SCRIPT, RESTART_SCRIPT
from shared_lib.config import load_env, write_env
from shared_lib.system import exec_command
from shared_lib.logger import log

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.jinja_env.add_extension("jinja2.ext.do")

# --- Custom Jinja Filter for Labels ---
ABBREVIATIONS = {
    "CF",
    "ID",
    "URL",
    "API",
    "IP",
    "DNS",
    "TCP",
    "TLS",
    "QUIC",
    "SSL",
    "WARP",
}


def format_label(key_string: str) -> str:
    parts = key_string.split("_")
    formatted_parts = []
    for part in parts:
        if part.upper() in ABBREVIATIONS:
            formatted_parts.append(part.upper())
        else:
            formatted_parts.append(part.capitalize())
    return " ".join(formatted_parts)


app.jinja_env.filters["format_label"] = format_label

# Load inbounds data and separate into Direct/CDN lists
direct_options = []
cdn_options = []
xray_inbounds_default = []

try:
    with open(INBOUNDS_JSON, "r", encoding="utf-8") as f:
        inbounds_data = json.load(f)
    for ib in inbounds_data:
        option_dict = {"name": ib["name"], "label": ib["name"]}
        if ib.get("cloudflare", False):
            cdn_options.append(option_dict)
            xray_inbounds_default.append(ib["name"])
        else:
            direct_options.append(option_dict)
            xray_inbounds_default.append(ib["name"])
except Exception as e:
    log.error(f"Error loading or processing {INBOUNDS_JSON}: {e}", hypothesisId="WEB")
    direct_options = [
        {"name": n, "label": n}
        for n in [
            "vless-tcp-tls-direct",
            "vless-hu-tls-direct",
            "vless-xhttp-quic-direct",
        ]
    ]
    cdn_options = [
        {"name": n, "label": n}
        for n in [
            "vmess-ws-cdn",
            "vless-hu-tls-cdn",
            "vless-xhttp-quic-cdn",
            "vless-xhttp-cdn",
        ]
    ]
    xray_inbounds_default = [
        "vmess-ws-cdn",
        "vless-tcp-tls-direct",
        "vless-hu-tls-direct",
        "vless-xhttp-quic-direct",
        "vless-hu-tls-cdn",
        "vless-xhttp-quic-cdn",
        "vless-xhttp-direct",
        "vless-xhttp-cdn",
    ]

CONFIG_SCHEMA: List[Dict[str, Any]] = [
    {
        "name": "METRIC_PUSH_METHOD",
        "type": "select",
        "default": "grafana_agent",
        "options": ["grafana_agent", "pushgateway"],
        "comment": 'Metric push method. Recommended: Grafana Agent. <a href="https://www.compassvpn.org/installation/configuration/#metric_push_method" target="_blank" rel="noopener noreferrer">Read More.</a>',
        "condition": None,
    },
    {
        "name": "GRAFANA_AGENT_REMOTE_WRITE_URL",
        "type": "text",
        "default": "",
        "placeholder": "https://prometheus-prod-XXX-grafana.grafana.net/api/prom/push",
        "comment": 'Endpoint URL for Grafana metrics. <a href="https://www.compassvpn.org/installation/configuration/#grafana_agent_remote_write_url" target="_blank" rel="noopener noreferrer">Read More.</a>',
        "condition": {"field": "METRIC_PUSH_METHOD", "value": "grafana_agent"},
    },
    {
        "name": "GRAFANA_AGENT_REMOTE_WRITE_USER",
        "type": "text",
        "default": "",
        "placeholder": "Your Grafana User ID",
        "comment": 'Username for Grafana metrics endpoint. <a href="https://www.compassvpn.org/installation/configuration/#grafana_agent_remote_write_user" target="_blank" rel="noopener noreferrer">Read More.</a>',
        "condition": {"field": "METRIC_PUSH_METHOD", "value": "grafana_agent"},
    },
    {
        "name": "GRAFANA_AGENT_REMOTE_WRITE_PASSWORD",
        "type": "password",
        "default": "",
        "placeholder": "Your Grafana API Key (glc_...)",
        "comment": 'Password Key for Grafana metrics endpoint. <a href="https://www.compassvpn.org/installation/configuration/#grafana_agent_remote_write_password" target="_blank" rel="noopener noreferrer">Read More.</a>',
        "condition": {"field": "METRIC_PUSH_METHOD", "value": "grafana_agent"},
    },
    {
        "name": "PUSHGATEWAY_URL",
        "type": "text",
        "default": "",
        "placeholder": "https://your-pushgateway-url:9091",
        "comment": 'URL of the Pushgateway server. <a href="https://www.compassvpn.org/installation/configuration/#pushgateway_url" target="_blank" rel="noopener noreferrer">Read More.</a>',
        "condition": {"field": "METRIC_PUSH_METHOD", "value": "pushgateway"},
    },
    {
        "name": "PUSHGATEWAY_AUTH_USER",
        "type": "text",
        "default": "",
        "placeholder": "Pushgateway Username",
        "comment": 'Username for Pushgateway authentication. <a href="https://www.compassvpn.org/installation/configuration/#pushgateway_auth_user" target="_blank" rel="noopener noreferrer">Read More.</a>',
        "condition": {"field": "METRIC_PUSH_METHOD", "value": "pushgateway"},
    },
    {
        "name": "PUSHGATEWAY_AUTH_PASSWORD",
        "type": "password",
        "default": "",
        "placeholder": "Pushgateway Password",
        "comment": 'Password for Pushgateway authentication. <a href="https://www.compassvpn.org/installation/configuration/#pushgateway_auth_password" target="_blank" rel="noopener noreferrer">Read More.</a>',
        "condition": {"field": "METRIC_PUSH_METHOD", "value": "pushgateway"},
    },
    {
        "name": "DONOR",
        "type": "text",
        "default": "compass",
        "placeholder": "e.g., my-server-01",
        "comment": 'Identifier for this server instance in metrics. <a href="https://www.compassvpn.org/installation/configuration/#donor" target="_blank" rel="noopener noreferrer">Read More.</a>',
    },
    {
        "name": "REDEPLOY_INTERVAL",
        "type": "select",
        "default": "1m",
        "options": ["1h", "4h", "1d", "7d", "14d", "1m", "3m"],
        "comment": 'How often configurations are reset (e.g., 7d for weekly). <a href="https://www.compassvpn.org/installation/configuration/#redeploy_interval" target="_blank" rel="noopener noreferrer">Read More.</a>',
    },
    {
        "name": "CF_API_TOKEN",
        "type": "password",
        "label": "Cloudflare API Token",
        "placeholder": "Enter Cloudflare API Token",
        "comment": 'API Token for Cloudflare access. Create with Zone.Zone:Read, Zone.DNS:Edit permissions. <a href="https://www.compassvpn.org/installation/configuration/#cf_api_token" target="_blank" rel="noopener noreferrer">Read More.</a>',
    },
    {
        "name": "CF_ZONE_ID",
        "type": "text",
        "label": "Cloudflare Zone ID",
        "placeholder": "Enter Cloudflare Zone ID",
        "comment": 'Zone ID for your domain in Cloudflare. <a href="https://www.compassvpn.org/installation/configuration/#cf_zone_id" target="_blank" rel="noopener noreferrer">Read More.</a>',
    },
    {
        "name": "CF_CLEAN_IP_DOMAIN",
        "type": "text",
        "label": "Cloudflare Clean IP Domain",
        "default": "npmjs.com",
        "comment": 'Domain to use for finding clean Cloudflare IPs. Default: npmjs.com. <a href="https://www.compassvpn.org/installation/configuration/#cf_clean_ip_domain" target="_blank" rel="noopener noreferrer">Read More.</a>',
    },
    {
        "name": "XRAY_OUTBOUND",
        "type": "select",
        "label": "Xray Outbound",
        "options": ["direct", "warp"],
        "default": "direct",
        "comment": 'Default outbound connection for Xray (Direct or Warp). <a href="https://www.compassvpn.org/installation/configuration/#xray_outbound" target="_blank" rel="noopener noreferrer">Read More.</a>',
    },
    {
        "name": "XRAY_INBOUNDS",
        "type": "checkbox_group",
        "label": "Enabled Xray Inbounds",
        "default": xray_inbounds_default,
        "comment": 'Select at least one inbound protocol to enable. <a href="https://www.compassvpn.org/installation/configuration/#xray_inbounds" target="_blank" rel="noopener noreferrer">Read More.</a>',
    },
    {
        "name": "SSL_PROVIDER",
        "type": "select",
        "default": "letsencrypt",
        "options": ["letsencrypt", "zerossl"],
        "comment": 'Certificate Authority for SSL certificates. <a href="https://www.compassvpn.org/installation/configuration/#ssl_provider" target="_blank" rel="noopener noreferrer">Read More.</a>',
    },
    {
        "name": "AUTO_UPDATE",
        "type": "toggle",
        "default": "on",
        "on_value": "on",
        "off_value": "off",
        "comment": 'Enable automatic updates for the agent software. <a href="https://www.compassvpn.org/installation/configuration/#auto_update" target="_blank" rel="noopener noreferrer">Read More.</a>',
    },
    {
        "name": "NGINX_PATH",
        "type": "text",
        "default": "compass",
        "placeholder": "e.g., myvpnpath (no slashes)",
        "comment": 'Internal NGINX routing path for the VPN service. <a href="https://www.compassvpn.org/installation/configuration/#nginx_path" target="_blank" rel="noopener noreferrer">Read More.</a>',
    },
    {
        "name": "NGINX_FAKE_WEBSITE",
        "type": "text",
        "default": "www.divar.ir",
        "placeholder": "e.g., www.example.com",
        "comment": 'Website to proxy for obfuscation (must NOT be behind major CDN). <a href="https://www.compassvpn.org/installation/configuration/#nginx_fake_website" target="_blank" rel="noopener noreferrer">Read More.</a>',
    },
    {
        "name": "CUSTOM_DNS",
        "type": "select_custom",
        "default": "controld",
        "options": ["default", "cf", "controld"],
        "comment": 'DNS resolver for the server. Use preset or custom URL. <a href="https://www.compassvpn.org/installation/configuration/#custom_dns" target="_blank" rel="noopener noreferrer">Read More.</a>',
    },
    {
        "name": "DEBUG",
        "type": "toggle",
        "default": "false",
        "on_value": "true",
        "off_value": "false",
        "comment": 'Enable verbose logging for troubleshooting. <a href="https://www.compassvpn.org/installation/configuration/#debug" target="_blank" rel="noopener noreferrer">Read More.</a>',
    },
]


def shutdown_server() -> None:
    os.kill(os.getpid(), signal.SIGINT)


UI_GROUPS: Dict[str, List[str]] = {
    "Metrics Configuration": [
        "METRIC_PUSH_METHOD",
        "GRAFANA_AGENT_REMOTE_WRITE_URL",
        "GRAFANA_AGENT_REMOTE_WRITE_USER",
        "GRAFANA_AGENT_REMOTE_WRITE_PASSWORD",
        "PUSHGATEWAY_URL",
        "PUSHGATEWAY_AUTH_USER",
        "PUSHGATEWAY_AUTH_PASSWORD",
    ],
    "General Settings": ["DONOR", "REDEPLOY_INTERVAL", "AUTO_UPDATE"],
    "Core Settings": [
        "XRAY_INBOUNDS",
        "XRAY_OUTBOUND",
    ],
    "Cloudflare Integration": ["CF_API_TOKEN", "CF_ZONE_ID", "CF_CLEAN_IP_DOMAIN"],
    "Advanced Settings": [
        "NGINX_FAKE_WEBSITE",
        "NGINX_PATH",
        "CUSTOM_DNS",
        "SSL_PROVIDER",
        "DEBUG",
    ],
}


@app.route("/", methods=["GET", "POST"])
def index() -> Any:
    current_config = load_env(str(ENV_FILE))

    config_data = {}
    for item in CONFIG_SCHEMA:
        key = item["name"]
        config_data[key] = current_config.get(key, item.get("default", ""))
        if item["type"] == "checkbox_group" and key not in current_config:
            config_data[key] = item.get("default", [])
        if (
            item["type"] == "checkbox_group"
            and key in current_config
            and isinstance(current_config[key], str)
        ):
            config_data[key] = current_config[key].split(",")

    if request.method == "POST":
        submitted_data = request.form.to_dict(flat=False)
        action = submitted_data.pop("action", [None])[0]
        env_to_save = current_config.copy()
        errors = []

        # Validate XRAY_INBOUNDS
        selected_inbounds = submitted_data.get("XRAY_INBOUNDS", [])
        if not selected_inbounds:
            errors.append("At least one Xray inbound must be enabled.")

        for key, values in submitted_data.items():
            if not values:
                continue
            schema_item = next(
                (item for item in CONFIG_SCHEMA if item["name"] == key), None
            )
            if not schema_item:
                continue

            value = values[0].strip()

            # Specific validation for NGINX_PATH
            if key == "NGINX_PATH":
                value = value.strip("/")
                if not value.isalnum() and "_" not in value and "-" not in value:
                    errors.append(
                        "NGINX Path must be alphanumeric (dashes/underscores allowed)."
                    )
                env_to_save[key] = value
                continue

            if schema_item["type"] == "checkbox_group":
                if not isinstance(values, list):
                    values = [values]
                env_to_save[key] = ",".join(values)
            elif key == "CUSTOM_DNS" and values[0] == "custom":
                custom_text = request.form.get("CUSTOM_DNS_TEXT", "").strip()
                env_to_save[key] = (
                    custom_text
                    if custom_text
                    else next(
                        (
                            item["default"]
                            for item in CONFIG_SCHEMA
                            if item["name"] == key
                        ),
                        "custom",
                    )
                )
            elif key in ["CUSTOM_DNS_TEXT", "REDEPLOY_INTERVAL_custom"]:
                continue
            else:
                env_to_save[key] = value

        if errors:
            for err in errors:
                log.warning(f"Validation failed: {err}", hypothesisId="WEB")
                flash(err, "danger")
            return redirect(url_for("index"))

        write_env(env_to_save, CONFIG_SCHEMA, str(ENV_FILE))

        if action == "save_close":
            flash(f"{os.path.basename(ENV_FILE)} saved successfully!", "success")
            shutdown_server()
            return """
                <div style="padding: 20px; font-family: sans-serif; background-color: rgb(139, 92, 246, 0.5); border-radius: 10px;">
                    <h3>Configuration Saved.</h3>
                    <p>Panel is closed. To reopen, run <strong>./start_panel.sh</strong> in the server terminal.</p>
                </div>
            """
        elif action == "save_close_bootstrap":
            flash(f"{os.path.basename(ENV_FILE)} saved successfully!", "success")
            newly_saved_config = load_env(str(ENV_FILE))
            identifier_value = newly_saved_config.get("IDENTIFIER", "").strip()

            script_to_run = RESTART_SCRIPT if identifier_value else BOOTSTRAP_SCRIPT

            full_script_path = str(script_to_run)
            script_basename = os.path.basename(full_script_path)

            if os.path.exists(full_script_path):
                try:
                    os.chmod(full_script_path, 0o755)
                    script_dir = os.path.dirname(full_script_path)
                    log.info(
                        f"Initiating script: {script_basename}",
                        hypothesisId="WEB",
                        path=full_script_path,
                    )
                    exec_command([full_script_path], cwd=script_dir)
                    flash(f"Successfully initiated: {script_basename}", "info")
                    script_message = (
                        f"Successfully initiated <strong>{script_basename}</strong>."
                    )
                except Exception as e:
                    log.error(
                        f"Error running {script_basename}: {e}", hypothesisId="WEB"
                    )
                    flash(f"Error trying to run {script_basename}: {e}", "danger")
                    script_message = (
                        f"Error trying to run <strong>{script_basename}</strong>: {e}"
                    )
            else:
                error_msg = f"Script not found: {full_script_path}"
                log.error(error_msg, hypothesisId="WEB")
                flash(error_msg, "danger")
                script_message = error_msg

            shutdown_server()
            return f"""
                <div style="padding: 20px; font-family: sans-serif; background-color: rgb(139, 92, 246, 0.5); border-radius: 10px;">
                    <h3>Configuration Saved.</h3>
                    <p>{script_message}</p>
                    <p>Panel is closed. To reopen, run <strong>./start_panel.sh</strong> in the server terminal.</p>
                 </div>
            """

        flash(f"{os.path.basename(ENV_FILE)} saved successfully!", "success")
        return redirect(url_for("index"))

    grouped_schema = {group: [] for group in UI_GROUPS}
    schema_dict = {item["name"]: item for item in CONFIG_SCHEMA}

    for group_title, keys_in_order in UI_GROUPS.items():
        for key in keys_in_order:
            if key in schema_dict:
                grouped_schema[group_title].append(schema_dict[key])

    return render_template(
        "index.html",
        schema=CONFIG_SCHEMA,
        config_data=config_data,
        ui_groups=grouped_schema,
        direct_options=direct_options,
        cdn_options=cdn_options,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
