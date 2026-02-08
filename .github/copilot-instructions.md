# Compass VPN Agent Coding Instructions

You are an expert AI developer working on the Compass VPN Agent, a multi-service Docker-based VPN management system.

## 🏗️ Architecture Big Picture
- **Multi-Service**: Orchestrated by `docker-compose.yml`. Key services: `xray-config` (logic/config generation), `xray` (core proxy), `nginx` (front-end proxy), `metric-forwarder`, and `web_panel`.
- **Centralized Logic**: `shared_lib` contains all common functionality (logging, networking, system, config) and is mounted as a volume in most containers.
- **State Management**: Configuration primarily lives in `env_file` (Key-Value pairs). Python services load this file using `shared_lib.config`.
- **Service Communication**: Services expose internal Flask APIs (e.g., `xray-config` on port 5000) to share state and metrics.

## 💻 Coding Patterns & Conventions

### 1. Python Path & Imports
Always ensure the project root is in `sys.path` before importing `shared_lib`.
```python
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from shared_lib.logger import log
```

### 2. Standardized Logging
Use `shared_lib.logger.log` instead of `print` or standard `logging`.
- Always provide a `hypothesisId` (e.g., `"DNS"`, `"CFG"`, `"WEB"`, `"SYS"`, `"XRAY"`) to categorize logs.
- Use keyword arguments for extra metadata.
```python
log.info("Starting DNS update", hypothesisId="DNS", domain="example.com")
```

### 3. Path Management
Never hardcode file paths. Use constants from `shared_lib.paths`.
- `ENV_FILE`: Path to the main configuration file.
- `INBOUNDS_JSON`: Definitions for Xray inbounds.
- `LOG_DIR`: Directory for all service logs (`/var/log/compassvpn`).

### 4. Configuration Handling
- Read config: `from shared_lib.config import load_env; env = load_env()`
- Write config: Use `write_env(env_data, schema)` from `shared_lib.config`.
- System Identifier: Use `shared_lib.config.get_identifier()` to get the unique agent ID.

### 5. Shared Library Modules
- `shared_lib.system`: Use `exec_command` for all shell operations.
- `shared_lib.network`: IP discovery and network checks.
- `shared_lib.xray`: Xray-specific logic (WARP registration, link parsing).

## 📡 Internal Service APIs
Services often expose internal APIs for state sharing and metrics:
- **xray-config**: Exports `/config` (Xray JSON), `/metrics` (Prometheus format), and `/valid-configs`.
- **web_panel**: Management UI that updates `env_file` and triggers restarts.

## 🛠️ Developer Workflow
- **Apply Changes**: Run `./restart.sh` to rebuild and restart all services.
- **Monitoring**: Run `./logs.sh` to follow logs from all services.
- **Bootstrapping**: Use `./bootstrap.sh` for first-time setup on a new VM.
- **Show Configs**: Run `./show_configs.sh` to see generated VPN links.

## ⚠️ Important Constraints
- **Container Environment**: Code often runs inside Docker. `shared_lib/paths.py` handles path overrides for container paths.
- **High Performance**: The system requires high `ulimits` (nofile: 65535) and specific `sysctls` defined in `docker-compose.yml`.
- **Security**: Services needing network modifications (Xray, Fail2ban) require `NET_ADMIN` capability.
