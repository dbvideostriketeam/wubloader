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
  database_tag:: "bb05e37", // tag for DB, which changes less and restarts are disruptive
  image_base:: "ghcr.io/ekimekim", // Change this to use images from a different source than the main one

  // For each service, whether to deploy that service.
  enabled:: {
    downloader: true,
    restreamer: true,
    backfiller: true,
    cutter: true,
    sheetsync: false,
    thrimshim: true,
    segment_coverage: true,
    playlist_manager: false,
    nginx: true,
    postgres: false,
    chat_archiver: false,
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

  // Local path to Thrimbletrimmer files. Useful if you're doing development on
  // Thrimbletrimmer (and probably not useful otherwise) to enable live updates
  // to Thrimbletrimmer without restarting/rebuilding Wubloader.
  // If you wish to use this, set this to the path containing the Thrimbletrimmer
  // web (HTML, CSS, JavaScript) files to serve (e.g. "/path/to/wubloader/thrimbletrimmer/").
  thrimbletrimmer_web_dev_path:: null,

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
    playlist_manager: 8007,
    nginx: 80,
    nginx_ssl: 443,
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

  ssl_certificate_path:: null, // set to path to SSL certs (cert chain + priv key in one file) to enable SSL

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
  db_readonly_user:: "vst-ro", // if empty, don't have a readonly account
  db_readonly_password:: "volunteer", // don't use default in production. Must not contain ' or \ as these are not escaped.  
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
  edit_url:: "http://thrimbletrimmer.codegunner.com/edit.html?id={}",

  // The timestamp corresponding to 00:00 in bustime
  bustime_start:: "1970-01-01T00:00:00Z",

  // The timestamps to start/end segment coverage maps at.
  // Generally 1 day before and 7 days after bus start.
  coverage_start:: "1969-12-31T00:00:00Z",
  coverage_end:: "1970-01-07T00:00:00Z",

  // Max hours ago to backfill, ie. do not backfill for times before this many hours ago.
  // Set to null to disable.
  backfill_max_hours_ago:: 24 * 30 * 6, // approx 6 months

  // The spreadsheet id and worksheet names for sheet sync to act on
  sheet_id:: "your_id_here",
  worksheets:: ["Tech Test & Preshow"] + ["Day %d" % n for n in std.range(1, 8)],
  playlist_worksheet:: "Tags",

  // A map from youtube playlist IDs to a list of tags.
  // Playlist manager will populate each playlist with all videos which have all those tags.
  // For example, tags ["Day 1", "Technical"] will populate the playlist with all Technical
  // youtube videos from Day 1.
  // Note that you can make an "all videos" playlist by specifying no tags (ie. []).
  playlists:: {
    "YOUR-PLAYLIST-ID": ["some tag"],
  },

  // Which upload locations should be added to playlists
  youtube_upload_locations:: [
    "desertbus",
    "youtube-manual",
  ],

  chat_archiver:: {
    // We currently only support archiving chat from one channel at once.
    // This defaults to the first channel in the $.channels list.
    channel: $.clean_channels[0],
    // Twitch user to log in as and path to oauth token
    user: "dbvideostriketeam",
    token_path: "./chat_token.txt",
  },

  // Extra options to pass via environment variables,
  // eg. log level, disabling stack sampling.
  env:: {
    // Uncomment this to set log level to debug
    // WUBLOADER_LOG_LEVEL: "DEBUG",
    // Uncomment this to enable stacksampling performance monitoring
    // WUBLOADER_ENABLE_STACKSAMPLER: "true",
  },

  // Now for the actual docker-compose config

  // The connection string for the database. Constructed from db_args.
  db_connect:: std.join(" ", [
    "%s='%s'" % [key, $.db_args[key]]
    for key in std.objectFields($.db_args)
  ]),

  // Cleaned up version of $.channels without importance markers
  clean_channels:: [std.split(c, '!')[0] for c in $.channels],

  // Image format helper
  get_image(name, tag=$.image_tag):: "%s/wubloader-%s:%s" % [
    $.image_base,
    name,
    tag,
  ],

  // docker-compose version
  version: "3",

  services: {

    [if $.enabled.downloader then "downloader"]: {
      image: $.get_image("downloader"),
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
      [if "downloader" in $.ports then "ports"]: ["%s:8001" % $.ports.downloader],
      environment: $.env,
    },

    [if $.enabled.restreamer then "restreamer"]: {
      image: $.get_image("restreamer"),
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
      environment: $.env,
    },

    [if $.enabled.backfiller then "backfiller"]: {
      image: $.get_image("backfiller"),
      // Args for the backfiller: set channel and qualities
      command: $.clean_channels +
      [
        "--base-dir", "/mnt",
        "--qualities", std.join(",", $.qualities),
        "--static-nodes", std.join(",", $.peers),
        "--backdoor-port", std.toString($.backdoor_port),
        "--node-database", $.db_connect,
        "--localhost", $.localhost,
      ] + (if $.backfill_max_hours_ago == null then [] else [
        "--start", std.toString($.backfill_max_hours_ago),
      ]),
      // Mount the segments directory at /mnt
      volumes: ["%s:/mnt" % $.segments_path],
      // If the application crashes, restart it.
      restart: "on-failure",
      // Expose on the configured host port by mapping that port to the default
      // port for backfiller, which is 8002.
      [if "backfiller" in $.ports then "ports"]: ["%s:8002" % $.ports.backfiller],
      environment: $.env,
    },

    [if $.enabled.cutter then "cutter"]: {
      image: $.get_image("cutter"),
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
      [if "cutter" in $.ports then "ports"]: ["%s:8003" % $.ports.cutter],
      environment: $.env,
    },

    [if $.enabled.thrimshim then "thrimshim"]: {
      image: $.get_image("thrimshim"),
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
      [if "thrimshim" in $.ports then "ports"]: ["%s:8004" % $.ports.thrimshim],
      environment: $.env,
    },

    [if $.enabled.sheetsync then "sheetsync"]: {
      image: $.get_image("sheetsync"),
      // Args for the sheetsync
      command: [
        "--backdoor-port", std.toString($.backdoor_port),
        "--allocate-ids",
        $.db_connect,
        "--playlist-worksheet", $.playlist_worksheet,
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
      [if "sheetsync" in $.ports then "ports"]: ["%s:8005" % $.ports.sheetsync],
      environment: $.env,
    },

    [if $.enabled.segment_coverage then "segment_coverage"]: {
      image: $.get_image("segment_coverage"),
      // Args for the segment_coverage
      command: $.clean_channels +
      [
        "--base-dir", "/mnt",
        "--qualities", std.join(",", $.qualities),
        "--first-hour", $.coverage_start,
        "--last-hour", $.coverage_end,
        // Render a html page showing all the images from all nodes
        "--make-page",
        "--connection-string", $.db_connect,
      ],
      // Mount the segments directory at /mnt
      volumes: ["%s:/mnt" % $.segments_path],
      // If the application crashes, restart it.
      restart: "on-failure",
      // Expose on the configured host port by mapping that port to the default
      // port for thrimshim, which is 8004.
      [if "segment_coverage" in $.ports then "ports"]: ["%s:8006" % $.ports.segment_coverage],
      environment: $.env,
    },

    [if $.enabled.playlist_manager then "playlist_manager"]: {
      image: $.get_image("playlist_manager"),
      // Args for the playlist_manager
      command: [
        "--backdoor-port", std.toString($.backdoor_port),
        "--upload-location-allowlist", std.join(",", $.youtube_upload_locations),
        $.db_connect,
        "/etc/wubloader-creds.json",
      ] + [
        "%s=%s" % [playlist, std.join(",", $.playlists[playlist])]
        for playlist in std.objectFields($.playlists)
      ],
      volumes: [
        // Mount the creds file into /etc
        "%s:/etc/wubloader-creds.json" % $.cutter_creds_file,
      ],
      // If the application crashes, restart it.
      restart: "on-failure",
      // Expose on the configured host port by mapping that port to the default
      // port for playlist_manager, which is 8007.
      [if "playlist_manager" in $.ports then "ports"]: ["%s:8007" % $.ports.playlist_manager],
      environment: $.env,
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
        playlist_manager: 8007,
      },
      image: $.get_image("nginx"),
      restart: "on-failure",
      ports: std.prune([
        if "nginx" in $.ports then "%s:80" % $.ports.nginx,
        if "nginx_ssl" in $.ports then "%s:443" % $.ports.nginx_ssl,
      ]),
      environment: $.env + {
        SERVICES: std.join("\n", [
          "%s %s" % [service, forward_ports[service]]
          for service in std.objectFields(forward_ports)
          if service in $.enabled && $.enabled[service]
        ]),
        THRIMBLETRIMMER: if $.thrimbletrimmer then "true" else "",
        SEGMENTS: if $.nginx_serve_segments then "/mnt" else "",
        SSL: if $.ssl_certificate_path != null then "/certs.pem" else "",
      },
      volumes: std.prune([
        if $.nginx_serve_segments then "%s:/mnt" % $.segments_path,
        if $.ssl_certificate_path != null then "%s:/certs.pem" % $.ssl_certificate_path,
        if $.thrimbletrimmer_web_dev_path != null then "%s:/etc/nginx/html/thrimbletrimmer" % $.thrimbletrimmer_web_dev_path,
      ]),
    },

    [if $.enabled.postgres then "postgres"]: {
      image: $.get_image("postgres", $.database_tag),
      restart: "on-failure",
      [if "postgres" in $.ports then "ports"]: ["%s:5432" % $.ports.postgres],
      environment: $.env + {
        POSTGRES_USER: $.db_super_user,
        POSTGRES_PASSWORD: $.db_super_password,
        POSTGRES_DB: $.db_args.dbname,
        PGDATA: "/mnt/database",
        WUBLOADER_USER: $.db_args.user,
        WUBLOADER_PASSWORD: $.db_args.password,
        REPLICATION_USER: $.db_replication_user,
        REPLICATION_PASSWORD: $.db_replication_password,
        READONLY_USER: $.db_readonly_user,
        READONLY_PASSWORD: $.db_readonly_password,
        MASTER_NODE: $.db_args.host,
      },
      volumes: ["%s:/mnt/database" % $.database_path, "%s:/mnt/wubloader" % $.segments_path],
      [if $.db_standby then "command"]: ["/standby_setup.sh"],
    },

    [if $.enabled.chat_archiver then "chat_archiver"]: {
      image: $.get_image("chat_archiver"),
      restart: "always",
      command: [$.chat_archiver.channel, $.chat_archiver.user, "/token"],
      volumes: ["%s:/mnt" % $.segments_path, "%s:/token" % $.chat_archiver.token_path],
    },

  },

}
