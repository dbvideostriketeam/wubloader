// This is a jsonnet file, it generates a docker-compose.yml file.
// To generate, run "make docker-compose.yml".

{

  // These are the important top-level settings.
  // Change these to configure the services.

  // Image tag (application version) to use.
  // By default, will use the current commit, ie. the same thing that ./build would tag
  // things it builds with.
  // Note: "latest" is not recommended in production, as you can't be sure what version
  // you're actually running, and must manually re-pull to get an updated copy.
  image_tag:: std.extVar("tag"),

  // For each service, whether to deploy that service.
  enabled:: {
    downloader: true,
    restreamer: true,
    backfiller: true,
    cutter: true,
    sheetsync: false,
    thrimshim: true,
    segment_coverage: true,
    nginx: true,
    postgres: false,
  },

  // Twitch channels to capture. The first one will be used as the default channel in the editor.
  // Channels suffixed with a '!' are considered "important" and will be retried more aggressively
  // and warned about if they're not currently streaming.
  channels:: ["desertbus!", "db_chief", "db_high", "db_audio", "db_bus"],

  // Stream qualities to capture
  qualities:: ["source", "480p"],

  // Local path to save segments to. Full path must already exist. Cannot contain ':'.
  // On OSX you need to change this to /private/var/lib/wubloader
  segments_path:: "/var/lib/wubloader/",

  // Local path to save database to. Full path must already exist. Cannot
  // contain ':'. If this directory is non-empty, the database will start with
  // the database in this directory and not run the setup scripts to create a 
  // new database.
  // On OSX you need to change this to /private/var/lib/wubloader_postgres/
  database_path:: "/var/lib/wubloader_postgres/",

  // The host's port to expose each service on.
  // Only nginx (and postgres if that is being deployed) needs to be externally accessible - the other non-database ports are routed through nginx.
  ports:: {
    restreamer: 8000,
    downloader: 8001,
    backfiller: 8002,
    cutter: 8003,
    thrimshim: 8004,
    sheetsync: 8005,
    segment_coverage: 8006,
    nginx: 80,
    postgres: 5432,
  },

  // The local port within each container to bind the backdoor server on.
  // You can exec into the container and telnet to this port to get a python shell.
  backdoor_port:: 1234,

  // Other nodes to always backfill from. You should not include the local node.
  // If you are using the database to find peers, you should leave this empty.
  peers:: [
  ],

  localhost:: "node_name", // the name in the nodes table of the database
  
  authentication:: true, // set to false to disable auth in thrimshim

  thrimbletrimmer:: true, // set to false to not have nginx serve thrimbletrimmer pages.

  nginx_serve_segments:: true, // set to false to not have nginx serve segments directly, letting restreamer do it instead.

  // Connection args for the database.
  // If database is defined in this config, host and port should be postgres:5432.
  db_args:: {
    user: "vst",
    password: "dbfh2019", // don't use default in production. Must not contain ' or \ as these are not escaped.
    host: "postgres",
    port: 5432,
    dbname: "wubloader",
  },

  // Other database arguments
  db_super_user:: "postgres", // only accessible from localhost
  db_super_password:: "postgres", // Must not contain ' or \ as these are not escaped.
  db_replication_user:: "replicate", // if empty, don't allow replication
  db_replication_password:: "standby", // don't use default in production. Must not contain ' or \ as these are not escaped.
  db_standby:: false, // set to true to have this database replicate another server

  // Path to a JSON file containing google credentials for cutter as keys
  // 'client_id', 'client_secret' and 'refresh_token'.
  cutter_creds_file:: "./google_creds.json",

  // Config for cutter upload locations. See cutter docs for full detail.
  cutter_config:: {
    desertbus: {type: "youtube"},
    unlisted: {type: "youtube", hidden: true, no_transcode_check: true},
  },
  default_location:: "desertbus",

  // Fixed tags to add to all videos
  video_tags:: ["DB13", "DB2019", "2019", "Desert Bus", "Desert Bus for Hope", "Child's Play Charity", "Child's Play", "Charity Fundraiser"],

  // The header to put at the front of video titles, eg. a video with a title
  // of "hello world" with title header "foo" becomes: "foo - hello world".
  title_header:: "DB2019",

  // The footer to put at the bottom of descriptions, in its own paragraph.
  description_footer:: "Uploaded by the Desert Bus Video Strike Team",

  // Path to a JSON file containing google credentials for sheetsync as keys
  // 'client_id', 'client_secret' and 'refresh_token'.
  // May be the same as cutter_creds_file.
  sheetsync_creds_file:: "./google_creds.json",

  // The URL to write to the sheet for edit links, with {} being replaced by the id
  edit_url:: "http://thrimbletrimmer.codegunner.com/?id={}",

  // The timestamp corresponding to 00:00 in bustime
  bustime_start:: "1970-01-01T00:00:00Z",

  // The spreadsheet id and worksheet names for sheet sync to act on
  sheet_id:: "your_id_here",
  worksheets:: ["Tech Test & Preshow"] + ["Day %d" % n for n in std.range(1, 7)],

  // Now for the actual docker-compose config

  // The connection string for the database. Constructed from db_args.
  db_connect:: std.join(" ", [
    "%s='%s'" % [key, $.db_args[key]]
    for key in std.objectFields($.db_args)
  ]),

  // Cleaned up version of $.channels without importance markers
  clean_channels:: [std.split(c, '!')[0] for c in $.channels],

  // docker-compose version
  version: "3",

  services: {

    [if $.enabled.downloader then "downloader"]: {
      image: "quay.io/ekimekim/wubloader-downloader:%s" % $.image_tag,
      // Args for the downloader: set channel and qualities
      command: $.channels +
      [  
        "--base-dir", "/mnt",
        "--qualities", std.join(",", $.qualities),
        "--backdoor-port", std.toString($.backdoor_port),
      ],
      // Mount the segments directory at /mnt
      volumes: ["%s:/mnt" % $.segments_path],
      // If the application crashes, restart it.
      restart: "on-failure",
      // Expose on the configured host port by mapping that port to the default
      // port for downloader, which is 8001.
      [if "downloader" in $.ports then "ports"]: ["%s:8001" % $.ports.downloader]
    },

    [if $.enabled.restreamer then "restreamer"]: {
      image: "quay.io/ekimekim/wubloader-restreamer:%s" % $.image_tag,
      // Mount the segments directory at /mnt
      volumes: ["%s:/mnt" % $.segments_path],
      // If the application crashes, restart it.
      restart: "on-failure",
      // Expose on the configured host port by mapping that port to the default
      // port for restreamer, which is 8000.
      [if "restreamer" in $.ports then "ports"]: ["%s:8000" % $.ports.restreamer],
      command: [
        "--base-dir", "/mnt",
        "--backdoor-port", std.toString($.backdoor_port),
      ],
    },

    [if $.enabled.backfiller then "backfiller"]: {
      image: "quay.io/ekimekim/wubloader-backfiller:%s" % $.image_tag,
      // Args for the backfiller: set channel and qualities
      command: $.clean_channels +
      [
        "--base-dir", "/mnt",
        "--qualities", std.join(",", $.qualities),
        "--static-nodes", std.join(",", $.peers),
        "--backdoor-port", std.toString($.backdoor_port),
        "--node-database", $.db_connect,
        "--localhost", $.localhost,
      ],
      // Mount the segments directory at /mnt
      volumes: ["%s:/mnt" % $.segments_path],
      // If the application crashes, restart it.
      restart: "on-failure",
      // Expose on the configured host port by mapping that port to the default
      // port for backfiller, which is 8002.
      [if "backfiller" in $.ports then "ports"]: ["%s:8002" % $.ports.backfiller]
    },

    [if $.enabled.cutter then "cutter"]: {
      image: "quay.io/ekimekim/wubloader-cutter:%s" % $.image_tag,
      // Args for the cutter: DB and creds
      command: [
        "--base-dir", "/mnt",
        "--backdoor-port", std.toString($.backdoor_port),
        "--tags", std.join(",", $.video_tags),
        "--name", $.localhost,
        $.db_connect,
        std.manifestJson($.cutter_config),
        "/etc/wubloader-creds.json",
      ],
      volumes: [
        // Mount the segments directory at /mnt
        "%s:/mnt" % $.segments_path,
      ] + [
        // Mount the creds file into /etc
        "%s:/etc/wubloader-creds.json" % $.cutter_creds_file,
      ],
      // If the application crashes, restart it.
      restart: "on-failure",
      // Expose on the configured host port by mapping that port to the default
      // port for cutter, which is 8003.
      [if "cutter" in $.ports then "ports"]: ["%s:8003" % $.ports.cutter]
    },

    [if $.enabled.thrimshim then "thrimshim"]: {
      image: "quay.io/ekimekim/wubloader-thrimshim:%s" % $.image_tag,
      // Args for the thrimshim: database connection string 
      command: [
        "--backdoor-port", std.toString($.backdoor_port),
        "--title-header", $.title_header,
        "--description-footer", $.description_footer,
        "--upload-locations", std.join(",", [$.default_location] + [
          location for location in std.objectFields($.cutter_config)
          if location != $.default_location
        ]),
        $.db_connect,
        $.clean_channels[0], // use first element as default channel
        $.bustime_start,
      ] + if $.authentication then [] else ["--no-authentication"],
      // Mount the segments directory at /mnt
      volumes: ["%s:/mnt" % $.segments_path],
      // If the application crashes, restart it.
      restart: "on-failure",
      // Expose on the configured host port by mapping that port to the default
      // port for thrimshim, which is 8004.
      [if "thrimshim" in $.ports then "ports"]: ["%s:8004" % $.ports.thrimshim]
    },

    [if $.enabled.sheetsync then "sheetsync"]: {
      image: "quay.io/ekimekim/wubloader-sheetsync:%s" % $.image_tag,
      // Args for the sheetsync
      command: [
        "--backdoor-port", std.toString($.backdoor_port),
        "--allocate-ids",
        $.db_connect,
        "/etc/wubloader-creds.json",
        $.edit_url,
        $.bustime_start,
        $.sheet_id,
      ] + $.worksheets,
      volumes: [
        // Mount the creds file into /etc
        "%s:/etc/wubloader-creds.json" % $.sheetsync_creds_file,
      ],
      // If the application crashes, restart it.
      restart: "on-failure",
      // Expose on the configured host port by mapping that port to the default
      // port for sheetsync, which is 8005.
      [if "sheetsync" in $.ports then "ports"]: ["%s:8005" % $.ports.sheetsync]
    },

    [if $.enabled.segment_coverage then "segment_coverage"]: {
      image: "quay.io/ekimekim/wubloader-segment_coverage:%s" % $.image_tag,
      // Args for the segment_coverage
      command: $.clean_channels +
      [
        "--base-dir", "/mnt",
        "--qualities", std.join(",", $.qualities),
      ],
      // Mount the segments directory at /mnt
      volumes: ["%s:/mnt" % $.segments_path],
      // If the application crashes, restart it.
      restart: "on-failure",
      // Expose on the configured host port by mapping that port to the default
      // port for thrimshim, which is 8004.
      [if "segment_coverage" in $.ports then "ports"]: ["%s:8006" % $.ports.segment_coverage]
    },

    [if $.enabled.nginx then "nginx"]: {
      # mapping of services to internal ports for nginx to forward
      local forward_ports = {
        restreamer: 8000,
        downloader: 8001,
        backfiller: 8002,
        cutter: 8003,
        thrimshim: 8004,
        sheetsync: 8005,
        segment_coverage: 8006,
      },
      image: "quay.io/ekimekim/wubloader-nginx:%s" % $.image_tag,
      restart: "on-failure",
      [if "nginx" in $.ports then "ports"]: ["%s:80" % $.ports.nginx],
      environment: {
        SERVICES: std.join("\n", [
          "%s %s" % [service, forward_ports[service]]
          for service in std.objectFields(forward_ports)
          if service in $.enabled && $.enabled[service]
        ]),
        THRIMBLETRIMMER: if $.thrimbletrimmer then "true" else "",
        SEGMENTS: if $.nginx_serve_segments then "/mnt" else "",
      },
      volumes: if $.nginx_serve_segments then ["%s:/mnt" % $.segments_path] else [],
    },

    [if $.enabled.postgres then "postgres"]: {
      image: "quay.io/ekimekim/wubloader-postgres:%s" % $.image_tag,
      restart: "on-failure",
      [if "postgres" in $.ports then "ports"]: ["%s:5432" % $.ports.postgres],
      environment: {
        POSTGRES_USER: $.db_super_user,
        POSTGRES_PASSWORD: $.db_super_password,
        POSTGRES_DB: $.db_args.dbname,
        PGDATA: "/mnt/database",
        WUBLOADER_USER: $.db_args.user,
        WUBLOADER_PASSWORD: $.db_args.password,
        REPLICATION_USER: $.db_replication_user,
        REPLICATION_PASSWORD: $.db_replication_password,
        MASTER_NODE: $.db_args.host,
      },
      volumes: ["%s:/mnt/database" % $.database_path, "%s:/mnt/wubloader" % $.segments_path],
      [if $.db_standby then "command"]: ["/standby_setup.sh"],
    },

  },

}
