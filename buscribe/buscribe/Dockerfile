FROM debian:11

RUN apt update &&\
    apt install -y python3 libpq-dev python3-pip curl unzip ffmpeg

COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

COPY buscribe/buscribe /tmp/buscribe
RUN pip install /tmp/buscribe && rm -r /tmp/buscribe

COPY models/extracted /usr/share/buscribe

ENTRYPOINT ["python3", "-m", "buscribe", "--base-dir", "/mnt"]
