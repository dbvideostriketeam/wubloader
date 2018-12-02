Wubloader is a system for saving, re-serving and cutting into videos of a target
twitch (or probably other HLS, but some twitch specifics are assumed) stream.

It was designed to serve the needs of the [Video Strike Team](https://vst.ninja)
as part of [Desert Bus For Hope](https://desertbus.org).

A full design doc can be read at [initial-design-doc.pdf](./initial-design-doc.pdf),
but a brief overview of the components:

* Downloader grabs segments from twitch and saves them to disk
* Restreamer serves segments from disk as well as playlist files allowing them to be streamed
* Backfiller queries restreamers of other servers in order to pick up segments this server doesn't have already,
  ie. it replicates missing segments.
* Cutter interacts with a database to perform cutting jobs
* Sheet Sync syncs specifc database columns to a google doc which is the primary operator interface.

### Usage

All components are built as docker images.
Components which access the disk expect a shared directory mounted at `/mnt`.

#### Configuration

Configuration is built into the docker images, and set during build by specifying a
YAML file `config.yaml` in the repository root directory.

See the provided example file for documentation of options.
