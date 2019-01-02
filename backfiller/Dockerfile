FROM alpine:3.7
# dependencies needed for compiling c extensions
RUN apk --update add py2-pip gcc python-dev musl-dev

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
COPY backfiller /tmp/backfiller
RUN pip install /tmp/backfiller && rm -r /tmp/backfiller

ENTRYPOINT ["python2", "-m", "backfiller", "--base-dir", "/mnt"]
