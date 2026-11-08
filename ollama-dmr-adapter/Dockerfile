FROM python:3.14.9-alpine@sha256:dbeb11d16bb95c3a7e3c25c842cb9f20cbc8c18f8be0461a4a0dcc861ad386a0

WORKDIR /app
COPY adapter.py /app/adapter.py

USER nobody
EXPOSE 11434

ENTRYPOINT ["python", "/app/adapter.py"]
