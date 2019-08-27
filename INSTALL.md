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

* `channel`, the Twitch channel to capture from
* `segments_path`, the local path to save segments to
* `db_args`, the arguments for connecting to the wubloader database
* `ports`, the ports to expose each service on. Only the `nginx` port (default on port 80) needs to be externally accessible for a non-database node as all the other services are routed through `nginx`.

To generate the `docker-compose.yml` file used by `docker-compose`, run `generate-docker-compose`

  `bash generate-docker-compose`
  
After making any changes to `docker-compose.jsonnet`, you will need to rerun `generate-docker-compose`.

By default the `downloader`, `restreamer`, `backfiller`, `cutter`, `thrimshim` and `nginx` services of the wubloader will be run. To change which services are run edit the `enabled` object in `docker-compose.jsonnet`. A complete wubloader set up also requires one and only one `database` service (though having a backup database is a good idea) and one and only one `sheetsync` service. TODO: explain how to setup database 

## Running the wubloader

To start the wubloader, simply run

  `docker-compose up`
  
To stop the wubloader and clean up, simply run

  `docker-compose down`
  
To backfill from a node, the other nodes need to know about it. The best way to do this is to add the node to the database's nodes table.
