FROM python:3.14.6-slim-bookworm

RUN \
    # Update apt and install wget
    apt-get update && apt-get install -y --no-install-recommends wget && \
    \
    # Detect architecture
    ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then \
        arch_name="amd64"; \
    elif [ "$ARCH" = "aarch64" ]; then \
        arch_name="arm64"; \
    else \
        echo "Unsupported architecture: $ARCH" >&2; \
        exit 1; \
    fi && \
    \
    # Download, install Grafana Agent, and cleanup downloaded file
    wget -L -O ga.deb "https://github.com/grafana/agent/releases/download/v0.44.2/grafana-agent-0.44.2-1.${arch_name}.deb" && \
    dpkg -i ga.deb && \
    rm ga.deb && \
    \
    # Remove wget and clean up
    apt-get purge -y wget && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt

RUN pip3 install --break-system-packages -r requirements.txt

COPY common.py common.py
COPY grafana_agent.py grafana_agent.py
COPY pushgateway.py pushgateway.py
COPY run.py run.py

CMD ["python3", "run.py"]
