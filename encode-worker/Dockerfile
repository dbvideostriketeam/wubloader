FROM docker.io/linuxserver/ffmpeg:version-7.1.1-cli
RUN apt update && \
    apt install -y --no-install-recommends \
    time \
    mediainfo \
    openssh-client \
    postgresql-client \
    sshpass \
    rsync \
    coreutils \
    ca-certificates && \
    apt autoremove -y && \
    apt clean && \
    rm -rf /var/lib/apt/lists/*

ENV WORKDIR=/encode
WORKDIR $WORKDIR

COPY encode-worker/encode-worker.sh /app/
RUN chmod +x /app/encode-worker.sh

# The script expects: NAME CONNINFO
# Example: docker run encode-worker "worker-1" "postgresql://user:pass@host/db"
ENTRYPOINT ["/app/encode-worker.sh"]
