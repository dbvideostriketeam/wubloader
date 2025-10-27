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

echo "Allow all users to use custom types"
sql "$POSTGRES_USER" -d "$POSTGRES_DB" <<-EOSQL
	ALTER DEFAULT PRIVILEGES GRANT USAGE ON TYPES TO PUBLIC;
EOSQL

echo "Installing audit log"
sql "$POSTGRES_USER" -d "$POSTGRES_DB" < /audit.sql

echo "Applying schema for $POSTGRES_DB"
sql "$POSTGRES_USER" -d "$POSTGRES_DB" < /schema.sql

echo "Creating $WUBLOADER_USER"
sql "$POSTGRES_USER" -d "$POSTGRES_DB" <<-EOSQL

CREATE USER $WUBLOADER_USER LOGIN PASSWORD '$WUBLOADER_PASSWORD';
GRANT CONNECT ON DATABASE $POSTGRES_DB TO $WUBLOADER_USER;
GRANT USAGE ON SCHEMA public, audit TO $WUBLOADER_USER;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO $WUBLOADER_USER;
GRANT SELECT ON TABLE audit.logged_actions TO $WUBLOADER_USER;

EOSQL


if [ -n "$REPLICATION_USER" ]; then
	echo "Creating $REPLICATION_USER"
	# allow the $REPLICATION user to replicate remotely
	echo "host replication $REPLICATION_USER all md5" >> "$PGDATA/pg_hba.conf"
	sql "$POSTGRES_USER" <<-EOSQL

	CREATE USER $REPLICATION_USER LOGIN REPLICATION PASSWORD '$REPLICATION_PASSWORD';

	EOSQL

	cat >> "$PGDATA/postgresql.conf" <<-EOF
	wal_keep_size = 128MB
	EOF

fi

if [ -e /mnt/wubloader/nodes.csv ]; then
	echo "Loading nodes from nodes.csv"
	sql "$POSTGRES_USER" -d "$POSTGRES_DB" <<-EOF
	COPY nodes FROM '/mnt/wubloader/nodes.csv' DELIMITER ',' CSV HEADER;
	EOF
fi

if [ -e /mnt/wubloader/roles.csv ]; then
	echo "Loading roles from roles.csv"
	sql "$POSTGRES_USER" -d "$POSTGRES_DB" <<-EOF
	COPY roles FROM '/mnt/wubloader/roles.csv' DELIMITER ',' CSV HEADER;
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
	-- The roles table contains private email addresses
	REVOKE SELECT ON TABLE roles FROM $READONLY_USER

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

if [ -n "$ENCODER_USER" ]; then
	echo "Creating $ENCODER_USER"
	echo "host all $ENCODER_USER all md5" >> "$PGDATA/pg_hba.conf"
	sql "$POSTGRES_USER" <<-EOSQL
		CREATE USER $ENCODER_USER WITH CONNECTION LIMIT 50 LOGIN PASSWORD '$ENCODER_PASSWORD';
		GRANT CONNECT ON DATABASE $POSTGRES_DB TO $ENCODER_USER;
		GRANT USAGE ON SCHEMA public TO $ENCODER_USER;
		GRANT SELECT ON TABLE encodes TO $ENCODER_USER;
		GRANT UPDATE ( dest_hash, claimed_by, claimed_at, finished_at ) ON TABLE encodes TO $ENCODER_USER;
	EOSQL
fi
