FROM postgres:latest
COPY postgres/setup.sh /docker-entrypoint-initdb.d/setup.sh
COPY postgres/standby_setup.sh /standby_setup.sh
RUN chmod 0666 /docker-entrypoint-initdb.d/setup.sh
RUN chmod 0700 /standby_setup.sh
