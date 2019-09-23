#! /bin/bash

set -e

# if postgres database does not exist in $PGDATA
if [ ! -s "$PGDATA/PG_VERSION" ]; then

	# get a binary backup of the database on $MASTER_NODE
	pg_basebackup -d "host=$MASTER_NODE password=$REPLICATION_PASSWORD port=5432 user=$REPLICATION_USER" -D ${PGDATA} -vP
	
	cat > ${PGDATA}/recovery.conf <<-EOF
	standby_mode = on
	primary_conninfo = 'host=$MASTER_NODE password=$REPLICATION_PASSWORD port=5432 user=$REPLICATION_USER'
	# touch this file to promote this node to master
	trigger_file = '/tmp/touch_to_promote_to_master'
	EOF

	chown postgres. ${PGDATA} -R
	chmod 700 ${PGDATA} -R

fi

# start postgres 
gosu postgres postgres
