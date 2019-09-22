#! /bin/bash


if [ ! -s "$PGDATA/PG_VERSION" ]; then

	pg_basebackup -d "host=$MASTER_NODE password=$REPLICATION_PASSWORD port=5432 user=$REPLICATION_USER" -D ${PGDATA} -vP

	set -e

	cat > ${PGDATA}/recovery.conf <<EOF

standby_mode = on
primary_conninfo = 'host=$MASTER_NODE password=$REPLICATION_PASSWORD port=5432 user=$REPLICATION_USER'
trigger_file = '/tmp/touch_me_to_promote_to_me_master'

EOF

	chown postgres. ${PGDATA} -R
	chmod 700 ${PGDATA} -R

fi

gosu postgres postgres
