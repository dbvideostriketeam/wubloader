FROM debian:latest

RUN apt update &&\
    apt install -y python3 libpq-dev python3-pip curl unzip ffmpeg

COPY ../common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

COPY buscribe /tmp/buscribe
RUN pip install /tmp/buscribe && rm -r /tmp/buscribe && \
    mkdir /usr/share/buscribe && cd /usr/share/buscribe && \
    curl -LO http://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip && \
    unzip vosk-model-small-en-us-0.15.zip && rm vosk-model-small-en-us-0.15.zip && \
    curl -LO https://alphacephei.com/vosk/models/vosk-model-spk-0.4.zip && \
    unzip vosk-model-spk-0.4.zip && rm vosk-model-spk-0.4.zip

ENTRYPOINT ["python3", "-m", "buscribe", "--base-dir", "/mnt"]
