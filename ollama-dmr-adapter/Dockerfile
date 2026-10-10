FROM python:3.14.8-alpine@sha256:f6a589d43c42b9e7f7dc67a12d37132491f362859a5d750607710cc56da3bc72

WORKDIR /app
COPY adapter.py /app/adapter.py

USER nobody
EXPOSE 11434

ENTRYPOINT ["python", "/app/adapter.py"]
