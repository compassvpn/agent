FROM grafana/alloy:v1.17.0 AS alloy-image

FROM python:3.14.6-slim-bookworm

COPY --from=alloy-image /bin/alloy /bin/alloy

COPY requirements.txt requirements.txt

RUN pip3 install --break-system-packages -r requirements.txt

COPY common.py common.py
COPY alloy.py alloy.py
COPY run.py run.py

CMD ["python3", "run.py"]
