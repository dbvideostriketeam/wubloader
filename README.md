Wubloader is a system for saving, re-serving and cutting into videos of a target
twitch (or probably other HLS, but some twitch specifics are assumed) stream.

It was designed to serve the needs of the [Video Strike Team](https://vst.ninja)
as part of [Desert Bus For Hope](https://desertbus.org).

A full design doc can be read at [initial-design-doc.pdf](./initial-design-doc.pdf),
but a brief overview of the components:

#### Shared Components

* `common` provides code shared between the other components.

#### Ingest
* `downloader` grabs segments from twitch and saves them to disk
* `restreamer` serves segments from disk as well as playlist files allowing them to be streamed
* `backfiller` queries restreamers of other servers in order to pick up segments this server doesn't have already,
  ie. it replicates missing segments.
* `chat_archiver` records twitch chat messages and merges them with records from other nodes.

#### Processing
* `sheetsync` syncs specifc database columns to a google doc which is the primary operator interface.
* `cutter` interacts with a database to perform cutting jobs
* `thrimshim` acts as an interface between the `thrimbletrimmer` editor and the database.
* `thrimbletrimmer` is a browser based video editor.
* `segment_coverage` regularly checks whether there is complete segment coverage for each hour. 
* `playlist_manager` adds videos to youtube playlists depending on tags.

#### Analysis
* `bus_analyzer` does OCR on the stream to produce timestamps of/for progress through the route.
* `buscribe` is back-end audio speech-to-text extraction.
* `buscribe_api` is the API provided for below to access the stored results of transcription.
* `buscribe-web` is the web frontend to interface with `buscribe`'s output (via `buscribe_api`)

#### Services
* `postgres` hosts a Postgres database to store events to be edited.
* `nginx` provides a webserver through which the other components are exposed to the outside world.
* `monitoring` provides dashboards to allow the wubloader to be monitored.

### Usage

All components are built as docker images.
Components which access the disk expect a shared directory mounted at `/mnt`.

A docker-compose file is provided to run all components. See `docker-compose.jsonnet`
to set configuration options, then generate the compose file with `./generate-docker-compose`.
Then run `docker-compose up`.

There is also a kubernetes-based option, but it is less configurable and only fully supports replication and editing nodes.
Basic support for running the database and playlist_manager has been added, but not tested.
See [k8s.jsonnet](./k8s.jsonnet) for details.

Further details of installing and configuring the backfiller are provided in [INSTALL.md](./INSTALL.md).
