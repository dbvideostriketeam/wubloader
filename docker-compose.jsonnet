// This is a jsonnet file, it generates a docker-compose.yml file.
// To generate, run "make docker-compose.yml".

{

  // These are the important top-level settings.
  // Change these to configure the services.

  // Image tag (application version) to use.
  // Note: "latest" is not reccomended in production, as you can't be sure what version
  // you're actually running, and must manually re-pull to get an updated copy.
  image_tag:: "latest",

  // Twitch channel to capture
  channel:: "desertbus",

  // Stream qualities to capture in addition to source.
  qualities:: ["480p"],

  // Local path to save segments to. Full path must already exist. Cannot contain ':'.
  segments_path:: "/var/lib/wubloader/",

  // The host's port to expose the restreamer on.
  restreamer_port:: 8080,


  // Now for the actual docker-compose config

  // docker-compose version
  version: "3",

  services: {

    downloader: {
      image: "quay.io/ekimekim/wubloader-downloader:%s" % $.image_tag,
      // Args for the downloader: set channel and qualities
      command: [
        $.channel,
        "--qualities", std.join(",", $.qualities),
      ],
      // Mount the segments directory at /mnt
      volumes: ["%s:/mnt" % $.segments_path],
      // If the application crashes, restart it.
      restart: "on-failure",
    },

    restreamer: {
      image: "quay.io/ekimekim/wubloader-restreamer:%s" % $.image_tag,
      // Mount the segments directory at /mnt
      volumes: ["%s:/mnt" % $.segments_path],
      // If the application crashes, restart it.
      restart: "on-failure",
      // Expose on the configured host port by mapping that port to the default
      // port for restreamer, which is 8000.
      ports: ["%s:8000" % $.restreamer_port],
    },

  },

}
