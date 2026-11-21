FROM python:3.14.10-alpine@sha256:5862d971d1f0ae26b258cefa4e893556b1d3aba81bd2ff30888704ad378bab67

WORKDIR /app
COPY adapter.py /app/adapter.py

USER nobody
EXPOSE 11434

ENTRYPOINT ["python", "/app/adapter.py"]
