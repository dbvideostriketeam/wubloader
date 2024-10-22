#! /bin/bash

set -e

sql() {
	local user
	user="$1"
	shift
	psql -v ON_ERROR_STOP=1 -U "$user" "$@"
}

# only allow the $WUBLOADER_USER to connect remotely rather than all users
sed -i "/host all all all/d" "$PGDATA/pg_hba.conf"
echo "host all $WUBLOADER_USER all md5" >> "$PGDATA/pg_hba.conf"

echo "Creating $WUBLOADER_USER"
sql "$POSTGRES_USER" <<-EOSQL

CREATE USER $WUBLOADER_USER LOGIN PASSWORD '$WUBLOADER_PASSWORD';

EOSQL


if [ -n "$REPLICATION_USER" ]; then
	echo "Creating $REPLICATION_USER"
	# allow the $REPLICATION user to replicate remotely
	echo "host replication $REPLICATION_USER all md5" >> "$PGDATA/pg_hba.conf"
	sql "$POSTGRES_USER" <<-EOSQL

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

echo "Applying schema for $POSTGRES_DB"
sql "$WUBLOADER_USER" -d "$POSTGRES_DB" < /schema.sql

if [ -a /mnt/wubloader/nodes.csv ]; then
	echo "Loading nodes from nodes.csv"
	sql "$POSTGRES_USER" -d "$POSTGRES_DB" <<-EOF
	COPY nodes FROM '/mnt/wubloader/nodes.csv' DELIMITER ',' CSV HEADER;
	EOF
fi

if [ -a /mnt/wubloader/editors.csv ]; then
	echo "Loading editors from editors.csv"
	sql "$POSTGRES_USER" -d "$POSTGRES_DB" <<-EOF
	COPY editors FROM '/mnt/wubloader/editors.csv' DELIMITER ',' CSV HEADER;
	EOF
fi

if [ -n "$READONLY_USER" ]; then
	echo "Creating $READONLY_USER"
	# allow $READONLY_USER to connect remotely
	echo "host all $READONLY_USER all md5" >> "$PGDATA/pg_hba.conf"
	sql "$POSTGRES_USER" -d "$POSTGRES_DB" <<-EOSQL

	CREATE USER $READONLY_USER WITH CONNECTION LIMIT 50 LOGIN PASSWORD '$READONLY_PASSWORD';
	GRANT CONNECT ON DATABASE $POSTGRES_DB TO $READONLY_USER;
	GRANT USAGE ON SCHEMA public TO $READONLY_USER;
	GRANT SELECT ON ALL TABLES IN SCHEMA public TO $READONLY_USER;

	EOSQL
fi

if [ -n "$BUSCRIBE_USER" ]; then
	echo "Creating $BUSCRIBE_USER"
	echo "host all $BUSCRIBE_USER all md5" >> "$PGDATA/pg_hba.conf"
	sql "$POSTGRES_USER" <<-EOSQL
		CREATE USER $BUSCRIBE_USER LOGIN PASSWORD '$BUSCRIBE_PASSWORD';
		CREATE DATABASE $BUSCRIBE_DB WITH OWNER $BUSCRIBE_USER;
	EOSQL

	echo "Applying schema for $BUSCRIBE_DB"
	sql "$BUSCRIBE_USER" -d "$BUSCRIBE_DB" < /buscribe.sql
fi
