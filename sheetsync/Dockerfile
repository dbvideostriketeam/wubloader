FROM alpine:3.14
# dependencies needed for compiling c extensions
# also busybox-extras for telnet for easier use of backdoor
RUN apk --update add py3-pip g++ python3-dev libffi-dev musl-dev postgresql-dev file make busybox-extras

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
RUN apk add postgresql-dev postgresql-client
COPY sheetsync /tmp/sheetsync
RUN pip install /tmp/sheetsync && rm -r /tmp/sheetsync

LABEL org.opencontainers.image.source https://github.com/ekimekim/wubloader
ENTRYPOINT ["python3", "-m", "sheetsync"]
