FROM postgres:12
COPY postgres/setup.sh /docker-entrypoint-initdb.d/setup.sh
COPY postgres/schema.sql /
RUN chmod 0666 /docker-entrypoint-initdb.d/setup.sh
COPY postgres/standby_setup.sh /standby_setup.sh
LABEL org.opencontainers.image.source https://github.com/dbvideostriketeam/wubloader
RUN chmod 0700 /standby_setup.sh
