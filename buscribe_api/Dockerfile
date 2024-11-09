FROM alpine:3.20
RUN rm /usr/lib/python3.12/EXTERNALLY-MANAGED
# dependencies needed for compiling c extensions
# also busybox-extras for telnet for easier use of backdoor
RUN apk --update add py3-pip g++ python3-dev libffi-dev musl-dev postgresql-dev file make busybox-extras

# should speed up installing python modules
RUN pip install --upgrade pip wheel

# Install gevent so that we don't need to re-install it when common changes
RUN pip install gevent

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
RUN apk add postgresql-dev postgresql-libs
COPY buscribe_api /tmp/buscribe_api
RUN pip install /tmp/buscribe_api && cp -r /tmp/buscribe_api/templates /templates \
    && rm -r /tmp/buscribe_api

ENTRYPOINT ["python3", "-m", "buscribeapi"]
