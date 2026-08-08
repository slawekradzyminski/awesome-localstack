FROM python:3.15.0b4-alpine@sha256:c40ec5a55436b283c1570e649ff40a8188e7e0221d7f285e624b20167c712ead

WORKDIR /app
COPY adapter.py /app/adapter.py

USER nobody
EXPOSE 11434

ENTRYPOINT ["python", "/app/adapter.py"]
