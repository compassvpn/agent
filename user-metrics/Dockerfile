FROM python:3.13.2-slim

WORKDIR /root

COPY ./user_metrics.py /root/

RUN chmod +x /root/user_metrics.py

EXPOSE 9551

CMD ["python3", "user_metrics.py"]
