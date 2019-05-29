FROM alpine:3.7
# dependencies needed for compiling c extensions
# also busybox-extras for telnet for easier use of backdoor
RUN apk --update add py2-pip gcc python-dev musl-dev busybox-extras

# Install common lib first as it changes less
COPY common /tmp/common
RUN pip install /tmp/common && rm -r /tmp/common

# Install actual application
COPY thrimshim /tmp/thrimshim
RUN pip install /tmp/thrimshim && rm -r /tmp/thrimshim

ENTRYPOINT ["python2", "-m", "thrimshim", "--base-dir", "/mnt"]
