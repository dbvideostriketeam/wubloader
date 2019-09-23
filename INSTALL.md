This is a guide on how to get the wubloader running.

All of the wubloader components are built as docker images and the provided docker-compose file can be used.

This installation guide is written assuming you are on a Linux-like operating system.

## Requirements
* `bash`

* `docker`

  https://docs.docker.com/install/

* `docker-compose`

  https://docs.docker.com/compose/install/
  
  
  
## Download the wubloader

You can download the latest version of the wubloader from github:

  https://github.com/ekimekim/wubloader/archive/master.zip
  
Alternatively if you have `git` installed you can clone the git repository:

  `git clone https://github.com/ekimekim/wubloader`
  
  
## Generate the docker-compose file

You can edit the `docker-compose.jsonnet` file to set the configuration options. Important options include:

* `channel`, the Twitch channel to capture from.
* `segments_path`, the local path to save segments to.
* `db_args`, the arguments for connecting to the wubloader database. You will likely need to update the `user`, `password` and `host` to match the database node that you are connecting to.
* `ports`, the ports to expose each service on. Only the `nginx` port (default on port 80) needs to be externally accessible for a non-database node as all the other services are routed through `nginx`.

To generate the `docker-compose.yml` file used by `docker-compose`, run `generate-docker-compose`

  `bash generate-docker-compose`
  
After making any changes to `docker-compose.jsonnet`, you will need to rerun `generate-docker-compose`.

By default the `downloader`, `restreamer`, `backfiller`, `cutter`, `thrimshim` and `nginx` services of the wubloader will be run. To change which services are run edit the `enabled` object in `docker-compose.jsonnet`. A complete wubloader set up also requires one and only one `database` service (though having a backup database is a good idea) and one and only one `sheetsync` service.

### Database setup

When setting up a database node, a number of database specific options can be set.

* `database_path`, the local path to save the database to. If this directory is empty then the database setups scripts will be run to create a new database. Otherwise, the database container will load the database stored in this folder.
* `db_args.user`, `db_args.password`, the username and password for the database user that the rest of the wubloader will connect to.
* `db_super_user`, `super_password`, the username and password for the database superuser that is only accessible from the local machine. 
* `db_replication_user`, `db_replication_password`, the username and password for the database user other nodes can connect as to replicate the database. If `db_replication_user` is an empty string, remote replication will be disabled.
* `db_standby`, If true this database node will replicate the database node given by `db_args.host`. 

It is recommended that the passwords be changed from the defaults in production.
A database node needs to expose its database on a port. By default this is `5432` but the port exposed to the outside can be changed in the `ports` object.

## Running the wubloader

To start the wubloader, simply run

  `docker-compose up`
  
To stop the wubloader and clean up, simply run

  `docker-compose down`

## Database setup

When setting up a database node, a number of database specific options can be set.

* `database_path`, the local path to save the database to. If this directory is empty then the database setups scripts will be run to create a new database. Otherwise, the database container will load the database stored in this folder.
* `db_args.user`, `db_args.password`, the username and password for the database user that the rest of the wubloader will connect to.
* `db_super_user`, `super_password`, the username and password for the database superuser that is only accessible from the local machine. 
* `db_replication_user`, `db_replication_password`, the username and password for the database user other nodes can connect as to replicate the database. If `db_replication_user` is an empty string, remote replication will be disabled.
* `db_standby`, If true this database node will replicate the database node given by `db_args.host`. 

It is recommended that the passwords be changed from the defaults in production.
A database node needs to expose its database on a port. By default this is `5432` but the port exposed to the outside can be changed in the `ports` object.

The `events` table will be automatically populated by the `sheetsync`. The startup script will attempt to populated the `nodes` and `editors` tables from the `nodes.csv` and `editors.csv` files in `segments_path` directory. The expected format for these files is:

```
nodes.csv

name,url,backfill_from
example,http://example.com,TRUE
```

```
editors.csv

name,email
example,example@gmail.com
```

Alternatively, nodes can be added manually to the database's `nodes` table:

`wubloader=> INSERT INTO nodes (name, url) VALUES ('example_name', 'http://example.com');`

and editors to the database's `editors` table:

`wubloader=> INSERT INTO editors (name, email) VALUES ('example', 'example@gmail.com');`

