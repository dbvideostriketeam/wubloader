FROM alpine:3.7
# dependencies needed for compiling c extensions
# also busybox-extras for telnet for easier use of backdoor
# and postgresql-dev as a dependency of psycopg2.
# Add postgresql-client for easier debugging of DB issues.
RUN apk --update add py2-pip gcc python-dev musl-dev busybox-extras postgresql-dev postgresql-client ffmpeg

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
COPY cutter /tmp/cutter
RUN pip install /tmp/cutter && rm -r /tmp/cutter

ENTRYPOINT ["python2", "-m", "cutter", "--base-dir", "/mnt"]
