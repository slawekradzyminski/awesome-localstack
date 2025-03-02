FROM ubuntu:22.04

ARG FASTSDCPU_VERSION=v1.0.0-beta.33

RUN apt update && apt-get install -y python3 python3-venv python3-wheel ffmpeg git

RUN git clone https://github.com/rupeshs/fastsdcpu /app \
    && cd app \
    && git checkout -b $FASTSDCPU_VERSION

WORKDIR /app

SHELL ["/bin/bash", "-c"]

RUN echo y | bash -x ./install.sh --disable-gui

# Ensure scripts have execution permissions
RUN chmod +x /app/start-webserver.sh

VOLUME /app/lora_models
VOLUME /app/controlnet_models
VOLUME /root/.cache/huggingface

ENV GRADIO_SERVER_NAME=0.0.0.0

EXPOSE 8000

CMD ["/app/start-webserver.sh"]
