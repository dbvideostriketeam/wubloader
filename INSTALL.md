This is a guide on how to get the wubloader running.

All of the wubloader components are built as docker images and the provided docker-compose file can be used.

This installation guide is written assuming you are on a Linux-like operating system.

## Requirements
* `bash`

* `git`

* `docker`

  https://docs.docker.com/install/

* `docker-compose`

  https://docs.docker.com/compose/install/
  
  
  
## Download the wubloader

Use github to clone the repository into a working directory.  If you intend to make changes, it's highly suggested you clone it into a fork of the repo on your own GitHub account.

  `git clone https://github.com/dbvideostriketeam/wubloader`
  
## Generate the docker-compose file

You can create a `docker-compose.local.jsonnet` file to override any configuration options from `docker-compose.jsonnet`, or edit `docker-compose.jsonnet` directly. Important options include:

* `channel`, the Twitch channel to capture from.
* `segments_path`, the local path to save segments to.
* `db_args`, the arguments for connecting to the wubloader database. You will likely need to update the `user`, `password` and `host` to match the database node that you are connecting to.
* `ports`, the ports to expose each service on. Only the `nginx` port (default on port 80) needs to be externally accessible for a non-database node as all the other services are routed through `nginx`.
* `localhost`, the name of the local machine as it appears in the database `nodes` table. This is prevent the node from backfilling from itself.
* `bustime_start`, the time the stream started.
* `cutter_config`, the configuration for cutter upload locations.
* `default_location`, the default cutter upload location.

Here is an example of how to set these and other configuration options in a `docker-compose.local.jsonnet` file:

```jsonnet
(import 'docker-compose.jsonnet') + {
  // In general, just list the variables you want to override using the same format as docker-compose.jsonnet
  image_tag:: '5b44a5a0c5765a63c52c7efc491892f6fba59f3f',
  localhost:: 'your_system_hostname',
  channels:: [
    'desertbus!',
  ],

  // You can edit multiple settings within a nested variable, without overriding the whole object, using +::
  db_args+:: {
    user: 'wubloader',
    password: 'correct horse battery staple',
  },
  chat_archiver+:: {
    user: 'Your_Twitch_Name',
    backfill: false,
  },
  enabled+:: {
    cutter: false,
    postgres: true,
    chat_archiver: true,
  },
}
```

There is no need to include any variables that you do not want to change, and you do not need to worry about other variables that may dynamically change based on your changes. For example, if you set:

```jsonnet
(import 'docker-compose.jsonnet') + {
  thrimbletrimmer_web_dev_path:: '/repos/wubloader/thrimbletrimmer/dist/',
}
```

`docker-compose.jsonnet` will later conditionally mount that path into the `nginx` container. It is not necessary for you to do anything special to make this happen - do not try to define `nginx.volumes` in your `docker-compose.local.jsonnet`. The conditionals in a `jsonnet` file see the final merged state of the variables, after your overrides, so overriding a variable in your `docker-compose.local.jsonnet` is as if you had changed that variable wherever in `docker-compose.jsonnet` it is defined.

To generate the `docker-compose.yml` file used by `docker-compose`, run `generate-docker-compose`

  `bash generate-docker-compose`
  
After making any changes to `docker-compose.jsonnet` or `docker-compose.local.jsonnet`, you will need to rerun `generate-docker-compose`.

By default the `downloader`, `restreamer`, `backfiller`, `cutter`, `thrimshim`, `segment_coverage` and `nginx` services of the wubloader will be run. To change which services are run edit the `enabled` object in `docker-compose.jsonnet`. A complete wubloader set up also requires one and only one `database` service (though having a backup database is a good idea), one and only one `sheetsync` service and one and only one `playlist_manager` service.

If you are running a `cutter` you will have to place the appropriate Google credentials in a JSON file given by the `cutter_creds_file` (google_creds.json in the root repo by default). Likewise, if you are running the `sheetsync` service, you will have to place the appropriate credentials in the JSON file pointed to by `sheetsync_creds_file` as well as set the appropriate `sheet_id` and `worksheets` for the Google sheet to sync with. You will also need to set the appropriate `edit_url` to access `thrimbletrimmer`.  

## Running Wubloader

To start the wubloader, simply run

  `docker-compose up`
  
To stop the wubloader and clean up, simply run

  `docker-compose down`

## Database Setup

When setting up a database node, a number of database specific options can be set.

* `database_path`, the local path to save the database to. If this directory is empty then the database setups scripts will be run to create a new database. Otherwise, the database container will load the database stored in this folder.
* `db_args.user`, `db_args.password`, the username and password for the database user that the rest of the wubloader will connect to.
* `db_super_user`, `super_password`, the username and password for the database superuser that is only accessible from the local machine. 
* `db_replication_user`, `db_replication_password`, the username and password for the database user other nodes can connect as to replicate the database. If `db_replication_user` is an empty string, remote replication will be disabled.
* `db_standby`, If true this database node will replicate the database node given by `db_args.host`. 

It is recommended that the passwords be changed from the defaults in production.
A database node needs to expose its database on a port. By default this is `5432` but the port exposed to the outside can be changed in the `ports` object.

The `events` table will be automatically populated by the `sheetsync`. If creating a new database, the startup script will attempt to populate the `nodes` and `editors` tables from the `nodes.csv` and `editors.csv` files in `segments_path` directory. The expected format for these files is:

```
nodes.csv

name,url,backfill_from
example,http://example.com,TRUE
```

```
editors.csv

email,name
example@gmail.com,example
```

Alternatively, nodes can be added manually to the database's `nodes` table:

`wubloader=> INSERT INTO nodes (name, url) VALUES ('example_name', 'http://example.com');`

and editors to the database's `editors` table:

`wubloader=> INSERT INTO editors (name, email) VALUES ('example', 'example@gmail.com');`

### Promoting the standby server

To promote the standby server to primary touch the trigger file in the docker container:

`docker exec wubloader_postgres_1 touch /tmp/touch_to_promote_to_master`

Be careful to prevent the original primary from restarting as another primary.

### Google sign-in client

To use your own Google OAuth Web Application client, set `google_client_id` in
`docker-compose.jsonnet`, regenerate Compose, and recreate thrimshim. Register
this deployment's browser origin (scheme, hostname, and port) in the client's
Authorized JavaScript origins. No client secret or redirect endpoint is needed.

Thrimshim passes the public client ID to the frontend through
`/thrimshim/auth-config` and uses the same ID to validate token audiences. When
running thrimshim outside Compose, set `GOOGLE_CLIENT_ID` in its environment.
The default remains the existing Wubloader client ID. The frontend and backend
must both be updated when first deploying this feature; later client ID changes
only require recreating thrimshim, without rebuilding the frontend.
