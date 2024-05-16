FROM python:3.11.9-bullseye

RUN wget https://github.com/grafana/agent/releases/download/v0.41.0/grafana-agent-0.41.0-1.amd64.deb && \
    dpkg -i grafana-agent-0.41.0-1.amd64.deb && \
    rm grafana-agent-0.41.0-1.amd64.deb

COPY requirements.txt requirements.txt

RUN pip3 install --break-system-packages -r requirements.txt

COPY . /

CMD ["python3", "run.py"]