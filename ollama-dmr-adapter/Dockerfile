FROM python:3.15.0a8-alpine@sha256:67a4b22b18852de8a9f668937641d2926e2dc9832b4a24ed29c9f5afb125251d

WORKDIR /app
COPY adapter.py /app/adapter.py

USER nobody
EXPOSE 11434

ENTRYPOINT ["python", "/app/adapter.py"]
