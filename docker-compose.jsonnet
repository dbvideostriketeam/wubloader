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

  // Stream qualities to capture
  qualities:: ["source", "480p"],

  // Local path to save segments to. Full path must already exist. Cannot contain ':'.
  // On OSX you need to change this to /private/var/lib/wubloader
  segments_path:: "/var/lib/wubloader/",

  // The host's port to expose each service on.
  // Only the restreamer needs to be externally accessible - the others are just for monitoring.
  ports:: {
    restreamer: 8080,
    downloader: 8001,
    backfiller: 8002,
  },

  // The local port within each container to bind the backdoor server on.
  // You can exec into the container and telnet to this port to get a python shell.
  backdoor_port:: 1234,

  // Other nodes to backfill from. You should not include the local node.
  peers:: [
    "http://wubloader.codegunner.com/"
  ],  

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
        "--backdoor-port", std.toString($.backdoor_port),
      ],
      // Mount the segments directory at /mnt
      volumes: ["%s:/mnt" % $.segments_path],
      // If the application crashes, restart it.
      restart: "on-failure",
      // Expose on the configured host port by mapping that port to the default
      // port for downloader, which is 8001.
      ports: ["%s:8001" % $.ports.downloader]
    },

    restreamer: {
      image: "quay.io/ekimekim/wubloader-restreamer:%s" % $.image_tag,
      // Mount the segments directory at /mnt
      volumes: ["%s:/mnt" % $.segments_path],
      // If the application crashes, restart it.
      restart: "on-failure",
      // Expose on the configured host port by mapping that port to the default
      // port for restreamer, which is 8000.
      ports: ["%s:8000" % $.ports.restreamer],
      command: [
        "--backdoor-port", std.toString($.backdoor_port),
      ],
    },

    backfiller: {
      image: "quay.io/ekimekim/wubloader-backfiller:%s" % $.image_tag,
      // Args for the backfiller: set channel and qualities
      command: [
        "--stream", $.channel,
        "-v", std.join(",", $.qualities),
        "--static-nodes", std.join(",", $.peers),
        "--backdoor-port", std.toString($.backdoor_port),
      ],
      // Mount the segments directory at /mnt
      volumes: ["%s:/mnt" % $.segments_path],
      // If the application crashes, restart it.
      restart: "on-failure",
      // Expose on the configured host port by mapping that port to the default
      // port for backfiller, which is 8002.
      ports: ["%s:8002" % $.ports.backfiller]
    },


  },

}

