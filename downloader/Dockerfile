FROM alpine:3.7
RUN apk --update add py2-pip

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
COPY downloader /tmp/downloader
RUN pip install /tmp/downloader && rm -r /tmp/downloader

ENTRYPOINT python2 -m downloader --base-dir /mnt
