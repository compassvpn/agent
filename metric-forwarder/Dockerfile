FROM python:3.11.9-bullseye

RUN arch=$(uname -m) && arch_name=$( [ "$arch" = "x86_64" ] && echo "amd64" ) || ( [ "$arch" = "aarch64" ] && echo "arm64" ) && \
    wget -O ga.deb https://github.com/grafana/agent/releases/download/v0.41.0/grafana-agent-0.41.0-1.$arch_name.deb && \
    dpkg -i ga.deb && \
    rm ga.deb

COPY requirements.txt requirements.txt

RUN pip3 install --break-system-packages -r requirements.txt

COPY . /

CMD ["python3", "run.py"]