#! /bin/bash

set -e

sed -i "/host all all all/d" "$PGDATA/pg_hba.conf"
echo "host replication $REPLICATION_USER all md5" >> "$PGDATA/pg_hba.conf"
echo "host all $WUBLOADER_USER all md5" >> "$PGDATA/pg_hba.conf"

psql -v ON_ERROR_STOP=1 -U postgres <<-EOSQL

CREATE USER $WUBLOADER_USER LOGIN PASSWORD '$WUBLOADER_PASSWORD';
CREATE USER $REPLICATION_USER LOGIN REPLICATION PASSWORD '$REPLICATION_PASSWORD';

EOSQL

cat >> ${PGDATA}/postgresql.conf <<EOF

wal_level = replica
archive_mode = on
archive_command = 'cd .'
max_wal_senders = 8
wal_keep_segments = 8

EOF
