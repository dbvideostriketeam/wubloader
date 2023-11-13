FROM alpine:3.14
# dependencies needed for compiling c extensions
# also busybox-extras for telnet for easier use of backdoor
RUN apk --update add py3-pip g++ python3-dev libffi-dev musl-dev postgresql-dev zlib-dev jpeg-dev file make busybox-extras

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Actual application
RUN apk add ffmpeg
COPY bus_analyzer /tmp/bus_analyzer
RUN pip install /tmp/bus_analyzer && cp -r /tmp/bus_analyzer/odo-digit-prototypes / && rm -r /tmp/bus_analyzer

LABEL org.opencontainers.image.source https://github.com/dbvideostriketeam/wubloader
ENTRYPOINT ["python3", "-m", "bus_analyzer"]