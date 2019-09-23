#! /bin/bash

set -e

sed -i "/host all all all/d" "$PGDATA/pg_hba.conf"
echo "host all $WUBLOADER_USER all md5" >> "$PGDATA/pg_hba.conf"

echo "Creating $WUBLOADER_USER"
psql -v ON_ERROR_STOP=1 -U postgres <<-EOSQL

CREATE USER $WUBLOADER_USER LOGIN PASSWORD '$WUBLOADER_PASSWORD';

EOSQL


if [ -n "$REPLICATION_USER" ]; then
	echo "Creating $REPLICATION_USER"
	echo "host replication $REPLICATION_USER all md5" >> "$PGDATA/pg_hba.conf"
	psql -v ON_ERROR_STOP=1 -U postgres <<-EOSQL

	CREATE USER $REPLICATION_USER LOGIN REPLICATION PASSWORD '$REPLICATION_PASSWORD';

	EOSQL

	cat >> ${PGDATA}/postgresql.conf <<-EOF
	wal_level = replica
	archive_mode = on
	archive_command = 'cd .'
	max_wal_senders = 8
	wal_keep_segments = 8
	EOF

fi

if [ -a /mnt/wubloader/nodes.csv ]; then
	echo "Loading nodes from nodes.csv"
	psql -v -U postgres -d ${POSTGRES_DB} <<-EOF
	CREATE TABLE IF NOT EXISTS nodes (
		name TEXT PRIMARY KEY,
		url TEXT NOT NULL,
		backfill_from BOOLEAN NOT NULL DEFAULT TRUE);
	COPY nodes FROM '/mnt/wubloader/nodes.csv' DELIMITER ',' CSV HEADER;
	ALTER TABLE nodes OWNER TO vst;
	EOF
fi

if [ -a /mnt/wubloader/editors.csv ]; then
	echo "Loading editors from editors.csv"
	psql -v -U postgres -d ${POSTGRES_DB} <<-EOF
	CREATE TABLE IF NOT EXISTS editors (
		email TEXT PRIMARY KEY,
		name TEXT NOT NULL);
	COPY editors FROM '/mnt/wubloader/editors.csv' DELIMITER ',' CSV HEADER;
	ALTER TABLE editors OWNER TO vst;
	EOF
fi

