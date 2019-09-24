#! /bin/bash

set -e

# only allow the $WUBLOADER_USER to connect remotely rather than all users
sed -i "/host all all all/d" "$PGDATA/pg_hba.conf"
echo "host all $WUBLOADER_USER all md5" >> "$PGDATA/pg_hba.conf"

echo "Creating $WUBLOADER_USER"
psql -v ON_ERROR_STOP=1 -U $POSTGRES_USER <<-EOSQL

CREATE USER $WUBLOADER_USER LOGIN PASSWORD '$WUBLOADER_PASSWORD';

EOSQL


if [ -n "$REPLICATION_USER" ]; then
	echo "Creating $REPLICATION_USER"
	# allow the $REPLICATION user to replicate remotely
	echo "host replication $REPLICATION_USER all md5" >> "$PGDATA/pg_hba.conf"
	psql -v ON_ERROR_STOP=1 -U $POSTGRES_USER <<-EOSQL

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
psql -v ON_ERROR_STOP=1 -U $WUBLOADER_USER -d $POSTGRES_DB <<-EOSQL
-- Create type if it doesn't already exist
DO \$\$ BEGIN
	CREATE TYPE event_state as ENUM (
		'UNEDITED',
		'EDITED',
		'CLAIMED',
		'FINALIZING',
		'TRANSCODING',
		'DONE'
	);
EXCEPTION WHEN duplicate_object THEN
	NULL;
END \$\$;

CREATE TABLE events (
	id UUID PRIMARY KEY,
	event_start TIMESTAMP,
	event_end TIMESTAMP,
	category TEXT NOT NULL DEFAULT '',
	description TEXT NOT NULL DEFAULT '',
	submitter_winner TEXT NOT NULL DEFAULT '',
	poster_moment BOOLEAN NOT NULL DEFAULT FALSE,
	image_links TEXT[] NOT NULL DEFAULT '{}', -- default empty array
	notes TEXT NOT NULL DEFAULT '',
	allow_holes BOOLEAN NOT NULL DEFAULT FALSE,
	uploader_whitelist TEXT[],
	upload_location TEXT CHECK (state = 'UNEDITED' OR upload_location IS NOT NULL),
	video_start TIMESTAMP CHECK (state IN ('UNEDITED', 'DONE') OR video_start IS NOT NULL),
	video_end TIMESTAMP CHECK (state IN ('UNEDITED', 'DONE') OR video_end IS NOT NULL),
	video_title TEXT CHECK (state IN ('UNEDITED', 'DONE') OR video_title IS NOT NULL),
	video_description TEXT CHECK (state IN ('UNEDITED', 'DONE') OR video_description IS NOT NULL),
	video_channel TEXT CHECK (state IN ('UNEDITED', 'DONE') OR video_channel IS NOT NULL),
	video_quality TEXT NOT NULL DEFAULT 'source',
	state event_state NOT NULL DEFAULT 'UNEDITED',
	uploader TEXT CHECK (state IN ('UNEDITED', 'EDITED', 'DONE') OR uploader IS NOT NULL),
	error TEXT,
	video_id TEXT,
	video_link TEXT CHECK (state != 'DONE' OR video_link IS NOT NULL),
	editor TEXT,
	edit_time TIMESTAMP CHECK (state = 'UNEDITED' OR editor IS NOT NULL),
	upload_time TIMESTAMP CHECK (state != 'DONE' OR upload_time IS NOT NULL)

);

-- Index on state, since that's almost always what we're querying on besides id
CREATE INDEX event_state ON events (state);

CREATE TABLE nodes (
	name TEXT PRIMARY KEY,
	url TEXT NOT NULL,
	backfill_from BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE editors (
	email TEXT PRIMARY KEY,
	name TEXT NOT NULL
);
EOSQL

if [ -a /mnt/wubloader/nodes.csv ]; then
	echo "Loading nodes from nodes.csv"
	psql -v ON_ERROR_STOP=1 -U $POSTGRES_USER -d $POSTGRES_DB <<-EOF
	COPY nodes FROM '/mnt/wubloader/nodes.csv' DELIMITER ',' CSV HEADER;
	EOF
fi

if [ -a /mnt/wubloader/editors.csv ]; then
	echo "Loading editors from editors.csv"
	psql -v ON_ERROR_STOP=1 -U $POSTGRES_USER -d $POSTGRES_DB <<-EOF
	COPY editors FROM '/mnt/wubloader/editors.csv' DELIMITER ',' CSV HEADER;
	EOF
fi

