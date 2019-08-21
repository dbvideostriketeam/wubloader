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
* `segments_path`, the local path to save segements to
* TODO add more

To generate the `docker-compose.yml` file used by `docker-compose`, run `generate-docker-compose`

  `bash generate-docker-compose`
  
After making any changes to `docker-compose.jsonnet`, you will need to rerun `generate-docker-compose`.

## Running the wubloader

To start the wubloader, simply run

  `docker-compose up`
  
To stop the wubloader and clean up, simply run

  `docker-compose down`
  
  
TODO what ports need to be exposed ....
