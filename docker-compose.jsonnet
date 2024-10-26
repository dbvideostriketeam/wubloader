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
  image_base:: "ghcr.io/dbvideostriketeam", // Change this to use images from a different source than the main one

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
    buscribe: false,
    buscribe_api: false,
    nginx: true,
    postgres: false,
    chat_archiver: false,
    schedulebot: false,
    tootbot: false,
    twitchbot: false,
    pubbot: false,
    bus_analyzer: false,
    graphs: false,
  },

  // Twitch channels to capture. The first one will be used as the default channel in the editor.
  // Channels suffixed with a '!' are considered "important" and will be retried more aggressively
  // and warned about if they're not currently streaming.
  channels:: ["desertbus!", "db_chief", "db_high", "db_audio", "db_bus"],

  backfill_only_channels:: [],

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
    chat_archiver: 8008,
    buscribe_api: 8010,
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
  db_readonly_user:: "readonly", // if empty, don't have a readonly account
  db_readonly_password:: "volunteer", // don't use default in production. Must not contain ' or \ as these are not escaped.  
  db_buscribe_dbname:: "buscribe",
  db_buscribe_user:: "buscribe", // if empty, buscribe database is not created and buscribe cannot be used.
  db_buscribe_password:: "transcription", // don't use default in production. Must not contain ' or \ as these are not escaped.
  db_standby:: false, // set to true to have this database replicate another server

  // Path to a file containing a twitch OAuth token to use when downloading streams.
  // This is optional (null to omit) but may be helpful to bypass ads.
  downloader_creds_file:: null,

  // Path to a JSON file containing google credentials for cutter as keys
  // 'client_id', 'client_secret' and 'refresh_token'.
  cutter_creds_file:: "./google_creds.json",

  // Config for cutter upload locations. See cutter docs for full detail.
  cutter_config:: {
    // Default
    desertbus: {type: "youtube", cut_type: "smart"},
    // Backup options for advanced use, if the smart cut breaks things.
    desertbus_slow: {type: "youtube", cut_type: "full"},
    desertbus_emergency: {type: "youtube", cut_type: "fast"},
    // Non-uploading backend that lets us modify manually-updated youtube videos
    "youtube-manual": {type: "youtube", no_uploader: true},
  },
  default_location:: "desertbus",
  // archive location is the default location for archive events,
  // only revelant if $.archive_worksheet is set.
  archive_location:: "archive",

  // Fixed tags to add to all videos
  video_tags:: ["DB13", "DB2019", "2019", "Desert Bus", "Desert Bus for Hope", "Child's Play Charity", "Child's Play", "Charity Fundraiser"],

  // The header to put at the front of video titles, eg. a video with a title
  // of "hello world" with title header "foo" becomes: "foo - hello world".
  title_header:: "DB2019",

  // The footer to put at the bottom of descriptions, in its own paragraph.
  description_footer:: |||
    https://www.desertbus.org
    Uploaded by the Desert Bus Video Strike Team
  |||,

  // Path to a JSON file containing google credentials for sheetsync as keys
  // 'client_id', 'client_secret' and 'refresh_token'.
  // May be the same as cutter_creds_file.
  sheet_creds_file:: "./google_creds.json",

  // Path to a text file containing the auth token for the streamlog server
  streamlog_creds_file:: "./streamlog_token.txt",

  // The URL to write to the sheet for edit links, with {} being replaced by the id
  edit_url:: "https://wubloader.example.com/thrimbletrimmer/edit.html?id={}",

  // The timestamp corresponding to 00:00 in bustime
  bustime_start:: "1970-01-01T00:00:00Z",

  // The timestamps to start/end segment coverage maps at.
  // Generally 1 day before and 7 days after bus start.
  coverage_start:: "1969-12-31T00:00:00Z",
  coverage_end:: "1970-01-07T00:00:00Z",

  // Max hours ago to backfill, ie. do not backfill for times before this many hours ago.
  // Set to null to disable.
  backfill_max_hours_ago:: 24 * 14, // 2 weeks, to avoid excessive backfill of old chat logs

  // Extra directories (besides segments) to backfill
  backfill_dirs:: ["emotes"],

  // Enable saving of media (images and videos - this can be large), either globally or split into
  // three options:
  // - From chat messages (in chat_archiver.download_media)
  // - From the image links column in the sheet (using sheetsync)
  // - Backfilled from other nodes
  download_media:: true,
  backfill_media:: $.download_media,
  download_sheet_links:: $.download_media,

  // The spreadsheet id and worksheet names for sheet sync to act on
  // Set to null to disable syncing from sheets.
  sheet_id:: "your_id_here",
  worksheets:: ["Tech Test & Preshow"] + ["Day %d" % n for n in std.range(1, 8)],
  playlist_worksheet:: "Tags",

  // The archive worksheet, if given, points to a worksheet containing events with a different
  // schema and alternate behaviour suitable for long-term archival videos instead of uploads.
  archive_worksheet:: "Video Trim Times",

  // Set to true to enable reverse-sync mode into Sheets, instead of syncing from it.
  sheet_reverse_sync:: false,

  // The StreamLog server and event id to use, or null to disable sync from StreamLog.
  streamlog_url:: "https://streamlog.example.com",
  streamlog_event:: "id_goes_here",

  // A map from youtube playlist IDs to a list of tags.
  // Playlist manager will populate each playlist with all videos which have all those tags.
  // For example, tags ["Day 1", "Technical"] will populate the playlist with all Technical
  // youtube videos from Day 1.
  // Note that you can make an "all videos" playlist by specifying no tags (ie. []).
  playlists:: {
    // Replaced entirely by tags sheet
  },

  // Which upload locations should be added to playlists
  youtube_upload_locations:: [
    "desertbus",
    "desertbus_slow",
    "desertbus_emergency",
    "youtube-manual",
  ],

  chat_archiver:: {
    // Twitch user to log in as and path to oauth token
    user: "dbvideostriketeam",
    token_path: "./chat_token.txt",
    // Whether to enable backfilling of chat archives to this node (if backfiller enabled)
    backfill: true,
    // Whether to enable downloading of media (images, videos, etc) that is posted in chat.
    download_media: $.download_media,
    // Channels to watch. Defaults to "all twitch channels in $.channels" but you can add extras.
    channels: [
      std.split(c, '!')[0]
      for c in $.channels
      if std.length(std.split(c, ":")) == 1
    ],
  },

  // The channel to use for bus_analyzer
  bus_channel:: "buscam",

  // The channel to run buscribe on. Future work: Have it run for more than one channel.
  buscribe_channel:: $.clean_channels[0],
  // Don't transcribe anything older than this time.
  // Note that if the database is not empty this time is ignored and buscribe continues
  // from the last known time.
  // Typically we set this to 1 month before bustime_start.
  buscribe_start:: "1970-01-01T00:00:00Z",

  zulip_url:: "https://chat.videostrike.team",

  schedulebot:: {
    // Creds for zulip api calls. Can't be a bot user due to annoying arbitrary restrictions.
    api_user: {
      email: "vst-zulip-bot@ekime.kim",
      api_key: "",
    },
    // Creds for the bot user to send messages as
    send_user: {
      email: "schedule-bot@chat.videostrike.team",
      api_key: "",
    },
    // Creds for accessing the schedule google sheet
    schedule_sheet_id: "",
    schedule_sheet_name: "All-Everything",
    google_credentials_file: "./google_creds.json",
    // Map from group names to zulip internal ids
    groups: {
      Sheeter: 16,
      Editor: 17,
      ChatOps: 18,
    },
    // Map from group id to 4 hard-coded lists of user ids, one per shift.
    groups_by_shift: {
    },
    // Map from schedule names to zulip user ids
    members: {
      ekimekim: 8,
    },
    // Extra args, see schedulebot.py.
    // --no-initial prevents re-posting current hour on restart.
    // --omega and --last enable special behaviour for omega shift and end of run, once known.
    args:: ["--no-initial"],
  },

  tootbot:: {
    zulip: {
      email: "tootbot-bot@chat.videostrike.team",
      api_key: "",
    },
    mastodon: {
      url: "https://kind.social",
      // Obtain an access token by running: python -m zulip_bots.tootbot get-access-token
      access_token: "",
    },
    args:: [],
  },

  twitchbot:: {
    twitch_username: $.chat_archiver.user,
    twitch_oauth_token: "",
    zulip_email: "twitch-chat-bot@chat.videostrike.team",
    zulip_api_key: "",
    args:: [],
  },

  pubbot:: {
    zulip_email: "blog-bot@chat.videostrike.team",
    zulip_api_key: "",
  },

  // template for donation data urls
  donation_url_template:: "https://example.com/DB{}/DB{}.json",

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
  make_db_connect(args):: std.join(" ", [
    "%s='%s'" % [key, args[key]]
    for key in std.objectFields(args)
  ]),
  db_connect:: $.make_db_connect($.db_args),
  db_connect_buscribe:: $.make_db_connect($.db_args + {
    user: $.db_buscribe_user,
    password: $.db_buscribe_password,
    dbname: $.db_buscribe_dbname,
  }),

  // Cleaned up version of $.channels without importance/type markers.
  // General form is CHANNEL[!][:TYPE:URL].
  clean_channels:: [std.split(std.split(c, ":")[0], '!')[0] for c in $.channels] + $.backfill_only_channels,

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
      ] + if $.downloader_creds_file != null then ["--twitch-auth-file", "/token"] else [],
      // Mount the segments directory at /mnt
      volumes: ["%s:/mnt" % $.segments_path]
        + if $.downloader_creds_file != null then ["%s:/token" % $.downloader_creds_file] else [],
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
        "--qualities", std.join(",", $.qualities + (if $.chat_archiver.backfill then ["chat"] else [])),
        "--extras", std.join(",",
          $.backfill_dirs
          + (if $.backfill_media then ["media"] else [])
        ),
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
      ]
      + (if $.authentication then [] else ["--no-authentication"])
      + (if $.archive_worksheet != null then [
        "--archive-sheet", $.archive_worksheet,
        "--archive-location", $.archive_location,
      ] else []),
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
      local sync_sheet_base = {
        name: if $.sheet_reverse_sync then "reverse-" else "",
        backend: "sheets",
        creds: "/etc/sheet-creds.json",
        sheet_id: $.sheet_id,
        allocate_ids: ! $.sheet_reverse_sync,
        reverse_sync: $.sheet_reverse_sync,
      },
      local sync_sheet = [
        sync_sheet_base + {
          name+: "sheet-events",
          type: "events",
          worksheets: $.worksheets,
          edit_url: $.edit_url,
          bustime_start: $.bustime_start,
          download_media: $.download_sheet_links,
        },
        sync_sheet_base + {
          name+: "sheet-playlists",
          type: "playlists",
          worksheets: [$.playlist_worksheet],
        },
      ] + (if $.archive_worksheet == null then [] else [
        sync_sheet_base + {
          name: "sheet-archive",
          type: "archive",
          worksheets: [$.archive_worksheet],
          edit_url: $.edit_url,
          bustime_start: $.bustime_start,
          // archive is never reverse sync
          allocate_ids: true,
          reverse_sync: false,
        }
      ]),
      local sync_streamlog_base = {
        backend: "streamlog",
        creds: "/etc/streamlog-token.txt",
        url: $.streamlog_url,
        event_id: $.streamlog_event,
      },
      local sync_streamlog = [
        sync_streamlog_base + {name: "streamlog-events", type: "events", download_media: $.download_sheet_links},
        sync_streamlog_base + {name: "streamlog-playlists", type: "playlists"},
      ],
      local config = (
          (if $.sheet_id != null then sync_sheet else [])
          + (if $.streamlog_url != null then sync_streamlog else [])
      ),
      image: $.get_image("sheetsync"),
      // Args for the sheetsync
      command: [
        "--backdoor-port", std.toString($.backdoor_port),
        $.db_connect,
      ]
      + (if $.download_sheet_links then ["--media-dir=/mnt"] else [])
      + std.map(std.manifestJson, config),
      volumes: std.prune([
        // Mount the creds file(s) into /etc
        if $.sheet_id != null then "%s:/etc/sheet-creds.json" % $.sheet_creds_file,
        if $.streamlog_url != null then "%s:/etc/streamlog-token.txt" % $.streamlog_creds_file,
        // Mount the segments media directory
        if $.download_sheet_links then "%s/media:/mnt" % $.segments_path,
      ]),
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
        chat_archiver: 8008,
        buscribe_api: 8010,
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
        BUSCRIBE_DB: $.db_buscribe_dbname,
        BUSCRIBE_USER: $.db_buscribe_user,
        BUSCRIBE_PASSWORD: $.db_buscribe_password,
        MASTER_NODE: $.db_args.host,
      },
      volumes: ["%s:/mnt/database" % $.database_path, "%s:/mnt/wubloader" % $.segments_path],
      [if $.db_standby then "command"]: ["/standby_setup.sh"],
    },

    [if $.enabled.chat_archiver then "chat_archiver"]: {
      image: $.get_image("chat_archiver"),
      restart: "always",
      command:
        [$.chat_archiver.user, "/token"]
        + $.chat_archiver.channels
        + ["--name", $.localhost]
        + (if $.chat_archiver.download_media then ["--download-media"] else []),
      volumes: ["%s:/mnt" % $.segments_path, "%s:/token" % $.chat_archiver.token_path],
      [if "chat_archiver" in $.ports then "ports"]: ["%s:8008" % $.ports.chat_archiver],
      environment: $.env,
    },

    [if $.enabled.buscribe then "buscribe"]: {
      image: $.get_image("buscribe"),
      restart: "always",
      command: [
        $.buscribe_channel,
        "--database", $.db_connect_buscribe,
        "--start-time", $.buscribe_start,
      ],
      volumes: ["%s:/mnt" % $.segments_path],
    },

    [if $.enabled.buscribe_api then "buscribe_api"]: {
      image: $.get_image("buscribe_api"),
      restart: "always",
      command: [
        "--database", $.db_connect_buscribe,
        "--bustime-start", $.bustime_start,
      ],
    },

    [if $.enabled.bus_analyzer then "bus_analyzer"]: {
      image: $.get_image("bus_analyzer"),
      restart: "always",
      command: ["main", $.db_connect, $.bus_channel, "--base-dir", "/mnt"],
      volumes: ["%s:/mnt" % $.segments_path],
      environment: $.env,
    },

    [if $.enabled.graphs then "graphs"]: {
      image: $.get_image("graphs"),
      restart: "always",
      command: [$.donation_url_template, "--base-dir", "/mnt/graphs"],
      volumes: ["%s:/mnt" % $.segments_path],
      environment: $.env,
    },

    local bot_service(name, config, args=[], subcommand=null) = {
      image: $.get_image("zulip_bots"),
      restart: "always",
      entrypoint: ["python3", "-m", "zulip_bots.%s" % name]
        + (if subcommand == null then [] else [subcommand])
        + [std.manifestJson(config)]
        + args,
      environment: $.env,
    },

    [if $.enabled.schedulebot then "schedulebot"]:
      bot_service("schedulebot", $.schedulebot + {
        url: $.zulip_url,
        start_time: $.bustime_start,
        schedule: "/schedule",
        google_credentials_file: "/creds.json",
      }, $.schedulebot.args) + {
        volumes: ["%s:/creds.json" % $.schedulebot.google_credentials_file],
      },

    [if $.enabled.tootbot then "tootbot"]:
      bot_service("tootbot", $.tootbot + {
        zulip+: { url: $.zulip_url },
      }, $.tootbot.args, subcommand="main"),

    [if $.enabled.twitchbot then "twitchbot"]:
      bot_service("twitchbot", $.twitchbot + {
        zulip_url: $.zulip_url,
      }),

    [if $.enabled.pubbot then "pubbot"]:
      bot_service("pubbot", $.pubbot + {
        zulip_url: $.zulip_url,
      }, ["/mnt/pubnub-log.json"]) + {
        volumes: ["%s:/mnt" % $.segments_path],
      },

  },

}
