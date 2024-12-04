FROM debian:12

RUN apt update &&\
    apt install -y python3 libpq-dev python3-pip curl unzip ffmpeg

RUN cd /tmp \
	&& curl \
		-LO http://alphacephei.com/vosk/models/vosk-model-en-us-0.22.zip \
		-LO http://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip \
		-LO https://alphacephei.com/vosk/models/vosk-model-spk-0.4.zip \
	&& mkdir /usr/share/buscribe \
	&& unzip vosk-model-en-us-0.22.zip -d /usr/share/buscribe \
	&& unzip vosk-model-small-en-us-0.15.zip -d /usr/share/buscribe \
	&& unzip vosk-model-spk-0.4.zip -d /usr/share/buscribe \
	&& rm *.zip

RUN rm /usr/lib/python3.11/EXTERNALLY-MANAGED

COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

COPY buscribe /tmp/buscribe
RUN pip install /tmp/buscribe && rm -r /tmp/buscribe

ENTRYPOINT ["python3", "-m", "buscribe", "--base-dir", "/mnt"]
