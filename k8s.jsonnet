// This is a jsonnet file, it generates kubernetes manifests.
// To generate and apply, run "jsonnet k8s.jsonnet | kubectl apply -f -"

// Note that this file is currently not as advanced as its docker-compose variant
// This file can only be used for replication nodes and editing nodes
// see config.enabled for more info on what components can be used

{
  kind: "List",
  apiVersion: "v1",
  config:: {
    // These are the important top-level settings.
    // Change these to configure the services.

    // Image tag (application version) to use.
    // Note: "latest" is not recommended in production, as you can't be sure what version
    // you're actually running, and must manually re-pull to get an updated copy.
    image_tag: "latest",

    image_base: "ghcr.io/dbvideostriketeam", // Change this to use images from a different source than the main one

    // image tag for postgres, which changes less
    // postgres shouldn't be restarted unless absolutely necessary
    database_tag: "bb05e37",

    // For each component, whether to deploy that component.
    enabled: {
      downloader: true,         # fetching segments from twitch.tv
      restreamer: true,         # serving segments for other wubloader nodes and/or thrimbletrimmer editor interface
      backfiller: true,         # fetching segments from other wubloader nodes
      cutter: false,            # performing cuts based on editor input
      sheetsync: false,         # syncing google sheets and postgres
      thrimshim: false,         # storing editor inputs in postgres
      segment_coverage: true,   # generating segment coverage graphs
      playlist_manager: false,  # auto-populating youtube playlists
      nginx: true,              # proxying between the various pods
      postgres: false,          # source-of-truth database
      chat_archiver: false,     # records twitch chat messages and merges them with records from other nodes
    },

    // Twitch channels to capture.
    // Channels suffixed with a '!' are considered "important" and will be retried more aggressively
    // and warned about if they're not currently streaming.
    channels: ["desertbus!", "db_chief", "db_high", "db_audio", "db_bus"],

    backfill_only_channels: [],

    // extra directories to backfill
    backfill_dirs: [],

    // Cleaned up version of $.channels without importance/type markers.
    // General form is CHANNEL[!][:TYPE:URL].
    clean_channels: [std.split(std.split(c, ":")[0], '!')[0] for c in $.config.channels] + $.config.backfill_only_channels,

    // Stream qualities to capture
    qualities: ["source", "480p"],

    // NFS settings for RWX (ReadWriteMany) volume for wubloader pods
    nfs_server: "nfs.example.com",            # server IP or hostname
    nfs_path: "/mnt/segments",                # path on server to mount
    nfs_capacity: "1T",                       # storage capacity to report to k8s
    # mount options to use (It is important to test these and adjust for optimal performance)
    # these options work reasonably well on a ZFS-backed NFS server with the default 128k block size
    nfs_mount_options: [
      "fsc",            # use FS-Cache to cache file data
      "noatime",        # don't update inode access times
      "nodiratime",     # don't update directory inode access times
      "vers=4",         # use NFSv4
      "proto=tcp",      # use TCP (default for NFSv4)
      "hard",           # retry NFS requests indefinitely
      "rsize=131072",   # 128kb read size
      "wsize=131072",   # 128kb write size
    ],

    // PVC template storage class for statefulset in postgres
    sts_storage_class_name: "longhorn",

    // Other nodes to always backfill from. You should not include the local node.
    // If you are using the database to find peers, you should leave this empty.
    peers: [
    ],

    // This node's name in the nodes table of the database
    localhost: "node_name",

    // The hostname to use in the Ingress
    ingress_host: "wubloader.example.com",

    // Set to true to let the ingress handle TLS
    ingress_tls: true,

    // Ingress class for ingress
    ingress_class_name: "nginx",

    // Uncomment and give a secretName for ingress, if required for ingress TLS
    //ingress_secret_name: "wubloader-tls",

    // Additional metadata labels for Ingress (cert-manager, etc.) - adjust as needed for your setup
    ingress_labels: {},

    // Connection args for the database.
    // If database is defined in this config, host and port should be wubloader-postgres:5432.
    db_args: {
      user: "vst",
      password: "dbfh2019", // don't use default in production. Must not contain ' or \ as these are not escaped.
      host: "postgres",
      port: 5432,
      dbname: "wubloader",
    },
    // Other database arguments
    db_super_user: "postgres",          // only accessible from localhost
    db_super_password: "postgres",      // Must not contain ' or \ as these are not escaped.
    db_replication_user: "replicate",   // if empty, don't allow replication
    db_replication_password: "standby", // don't use default in production. Must not contain ' or \ as these are not escaped.
    db_readonly_user: "vst-ro",         // if empty, don't have a readonly account
    db_readonly_password: "volunteer",  // don't use default in production. Must not contain ' or \ as these are not escaped.  
    db_standby: false,                  // set to true to have this database replicate another server

    // path to a JSON file containing google credentials for cutter as keys
    // 'client_id', 'client_secret', and 'refresh_token'.
    cutter_creds: import "./google_creds.json",

    // Path to a JSON file containing google credentials for sheetsync as keys
    // 'client_id', 'client_secret' and 'refresh_token'.
    // May be the same as cutter_creds_file.
    sheetsync_creds: import "./google_creds.json",

    // Path to a file containing a twitch OAuth token to use when downloading streams.
    // This is optional (null to omit) but may be helpful to bypass ads.
    downloader_creds_file: null,

    // The URL to write to the sheet for edit links, with {} being replaced by the id
    edit_url: "https://wubloader.example.com/edit.html?id={}",

    // The spreadsheet ID and worksheet names for sheetsync to act on
    sheet_id: "your_id_here",
    worksheets: ["Tech Test & Preshow"] + ["Day %d" % n for n in std.range(1, 8)],
    playlist_worksheet: "Tags",

    // The archive worksheet, if given, points to a worksheet containing events with a different
    // schema and alternate behaviour suitable for long-term archival videos instead of uploads.
    archive_worksheet: "Video Trim Times",

    // Fixed tags to add to all videos
    video_tags: ["DB17", "DB2023", "2023", "Desert Bus", "Desert Bus for Hope", "Child's Play Charity", "Child's Play", "Charity Fundraiser"],

   // The timestamp corresponding to 00:00 in bustime
    bustime_start: "1970-01-01T00:00:00Z",

    // The timestamps to start/end segment coverage maps at.
    // Generally 1 day before and 7 days after bus start.
    coverage_start: "1969-12-31T00:00:00Z",
    coverage_end: "1970-01-07T00:00:00Z",

    // Max hours ago to backfill, ie. do not backfill for times before this many hours ago.
    // Set to null to disable.
    backfill_max_hours_ago: 24 * 14, // approx 14 days

    // Extra options to pass via environment variables,
    // eg. log level, disabling stack sampling.
    env: {
      // Uncomment this to set log level to debug
      // WUBLOADER_LOG_LEVEL: "DEBUG",
      // Uncomment this to enable stacksampling performance monitoring
      // WUBLOADER_ENABLE_STACKSAMPLER: "true",
    },

    // A map from youtube playlist IDs to a list of tags.
    // Playlist manager will populate each playlist with all videos which have all those tags.
    // For example, tags ["Day 1", "Technical"] will populate the playlist with all Technical
    // youtube videos from Day 1.
    // Note that you can make an "all videos" playlist by specifying no tags (ie. []).
    playlists: {
      // Replaced entirely by tags sheet
    },

    // Which upload locations should be added to playlists
    youtube_upload_locations: [
      "desertbus",
      "desertbus_slow",
      "desertbus_emergency",
      "youtube-manual",
    ],

    // Config for cutter upload locations. See cutter docs for full detail.
    cutter_config: {
      // Default
      desertbus: {type: "youtube", cut_type: "smart"},
      // Backup options for advanced use, if the smart cut breaks things.
      desertbus_slow: {type: "youtube", cut_type: "full"},
      desertbus_emergency: {type: "youtube", cut_type: "fast"},
    },
    default_location: "desertbus",
    // archive location is the default location for archive events,
    // only revelant if $.archive_worksheet is set.
    archive_location: "archive",

    // The header to put at the front of video titles, eg. a video with a title
    // of "hello world" with title header "foo" becomes: "foo - hello world".
    title_header: "DB2023",

    // The footer to put at the bottom of descriptions, in its own paragraph
    description_footer: "Uploaded by the Desert Bus Video Strike Team",

    // Chat archiver settings
    chat_archiver: {
      // Twitch user to log in as and path to oauth token
      user: "dbvideostriketeam",
      token: importstr "./chat_token.txt",
      // Whether to enable backfilling of chat archives to this node (if backfiller enabled)
      backfill: true,
      // Channels to watch. Defaults to "all twitch channels in $.channels" but you can add extras.
      channels: [
        std.split(c, '!')[0]
        for c in $.channels
        if std.length(std.split(c, ":")) == 1
      ],
    },
  },

  // A few derived values.

  // The connection string for the database. Constructed from db_args.
  db_connect:: std.join(" ", [
    "%s='%s'" % [key, $.config.db_args[key]]
    for key in std.objectFields($.config.db_args)
  ]),

  // Cleaned up version of $.channels without importance markers
  clean_channels:: [std.split(c, '!')[0] for c in $.config.channels],

  // k8s-formatted version of env dict
  env_list:: [
    {name: key, value: $.config.env[key]}
    for key in std.objectFields($.config.env)
  ],

  // Which upload locations have type youtube, needed for playlist_manager
  youtube_upload_locations:: [
    location for location in std.objectFields($.config.cutter_config)
    if $.config.cutter_config[location].type == "youtube"
  ],

  // This function generates deployments for each service, since they only differ slightly,
  // with only a different image, CLI args and possibly env vars.
  // The image name is derived from the component name
  // (eg. "downloader" is ghcr.io/dbvideostriketeam/wubloader-downloader)
  // so we only pass in name as a required arg.
  // Optional kwargs work just like python.
  deployment(name, args=[], env=[], volumes=[], volumeMounts=[], resources={}):: {
    kind: "Deployment",
    apiVersion: "apps/v1",
    metadata: {
      namespace: "wubloader",
      name: name,
      labels: {app: "wubloader", component: name},
    },
    spec: {
      replicas: 1,
      selector: {
        matchLabels: {app: "wubloader", component: name},
      },
      template: {
        metadata: {
          labels: {app: "wubloader", component: name},
        },
        spec: {
          containers: [
            {
              name: name,
              // segment-coverage is called segment_coverage in the image, so replace - with _
              // ditto for playlist-manager
              image: "%s/wubloader-%s:%s" % [$.config.image_base, std.strReplace(name, "-", "_"), $.config.image_tag],
              args: args,
              resources: resources,
              volumeMounts: [{name: "data", mountPath: "/mnt"}] + volumeMounts,
              env: $.env_list + env, // main env list combined with any deployment-specific ones
            },
          ],
          volumes: [
            {
              name: "data",
              persistentVolumeClaim: {"claimName": "segments"},
            },
          ] + volumes
        },
      },
    },
  },

  // This function generates a Service object for each service
  service(name):: {
    kind: "Service",
    apiVersion: "v1",
    metadata: {
      namespace: "wubloader",
      name: name,
      labels: {app: "wubloader", component: name},
    },
    spec: {
      selector: {app: "wubloader", component: name},
      ports: if name == "postgres" then [{name: "postgres", port: 5432, targetPort: 5432},] else [{name: "http", port: 80, targetPort: 80}],
    },
  },

  // This function generates a StatefulSet object (for postgres)
  statefulset(name, args=[], env=[]):: {
    kind: "StatefulSet",
    apiVersion: "apps/v1",
    metadata: {
      namespace: "wubloader",
      name: name,
      labels: {app: "wubloader", component: name},
    },
    spec: {
      replicas: 1,
      selector: {
        matchLabels: {app: "wubloader", component: name},
      },
      serviceName: name,
      template: {
        metadata: {
          labels: {app: "wubloader", component: name},
        },
        spec: {
          containers: [
            {
              name: name,
              image: "%s/wubloader-%s:%s" % [$.config.image_base, name, $.config.database_tag],
              args: args,
              env: $.env_list + env, // main env list combined with any statefulset-specific ones
              volumeMounts: [
                // tell use a subfolder in the newly provisioned PVC to store postgres DB
                // a newly provisioned ext4 PVC will be non-empty, so postgres fails to start if we don't use a subfolder
                {name: "database", mountPath: "/mnt/database", subPath: "postgres"},
                {name: "segments", mountPath: "/mnt/wubloader"}
              ],
            },
          ],
          volumes: [
            {
              name: "segments",
              persistentVolumeClaim: {"claimName": "segments"},
            },
          ],
        },
      },
      volumeClaimTemplates: [
        {
          metadata: {
            namespace: "wubloader",
            name: "database"
          },
          spec: {
            accessModes: ["ReadWriteOnce"],
            resources: {
              requests: {
                storage: "50GiB"
              },
            },
            storageClassName: $.config.sts_storage_class_name
          },
        },
      ],
    },
  },

  // The actual manifests to output, filtering out "null" from disabled components.
  items: [comp for comp in $.components if comp != null],
  
  // These are all the deployments and services. 
  // Note that all components work fine if multiple are running
  // (they may duplicate work, but not cause errors by stepping on each others' toes).
  components:: [
    // A namespace where all the things go
    {
      "apiVersion": "v1",
      "kind": "Namespace",
      "metadata": {
        "name": "wubloader"
      },
    },
    // The downloader watches the twitch stream and writes the HLS segments to disk
    if $.config.enabled.downloader then $.deployment("downloader", args=$.config.channels + [
      "--base-dir", "/mnt",
      "--qualities", std.join(",", $.config.qualities),
      "--metrics-port", "80",
    ]+ if $.config.downloader_creds_file != null then ["--auth-file", "/etc/creds/downloader_token.txt"] else [],
    volumes=[
      {name:"credentials", secret: {secretName: "credentials"}}
    ],
    volumeMounts=[
      {mountPath: "/etc/creds", name: "credentials"},
    ]),
    // The restreamer is a http server that fields requests for checking what segments exist
    // and allows HLS streaming of segments from any requested timestamp
    if $.config.enabled.restreamer then $.deployment("restreamer", args=[
      "--base-dir", "/mnt",
      "--port", "80",
    ]),
    // The backfiller periodically compares what segments exist locally to what exists on
    // other nodes. If it finds ones it doesn't have, it downloads them.
    // It can talk to the database to discover other wubloader nodes, or be given a static list.
    if $.config.enabled.backfiller then $.deployment("backfiller", args=$.config.clean_channels + [
      "--base-dir", "/mnt",
      "--qualities", std.join(",", $.config.qualities + (if $.config.chat_archiver.backfill then ["chat"] else [])),
      "--extras", std.join(",", $.config.backfill_dirs),
      "--static-nodes", std.join(",", $.config.peers),
      "--node-database", $.db_connect,
      "--localhost", $.config.localhost,
      "--metrics-port", "80",
    ] + (if $.config.backfill_max_hours_ago == null then [] else [
      "--start", std.toString($.config.backfill_max_hours_ago),
    ])),
    // Segment coverage is a monitoring helper that periodically scans available segments
    // and reports stats. It also creates a "coverage map" image to represent this info.
    // It puts this in the segment directory where nginx will serve it.
    if $.config.enabled.segment_coverage then $.deployment("segment-coverage", args=$.config.clean_channels + [
      "--base-dir", "/mnt",
      "--qualities", std.join(",", $.config.qualities),
      "--metrics-port", "80",
      "--first-hour", $.config.coverage_start,
      "--last-hour", $.config.coverage_end,
      // Render a html page showing all the images from all nodes
      "--make-page",
      "--connection-string", $.db_connect,
    ]),
    // Thrimshim acts as an interface between the thrimbletrimmer editor and the database
    // It is needed for thrimbletrimmer to be able to get unedited videos and submit edits
    if $.config.enabled.thrimshim then $.deployment("thrimshim", args=[
      "--port", "80",
      "--title-header", $.config.title_header,
      "--description-footer", $.config.description_footer,
      "--upload-locations", std.join(",", [$.config.default_location] + [
        location for location in std.objectFields($.config.cutter_config)
        if location != $.config.default_location
      ]),
      $.db_connect,
      $.config.clean_channels[0],  // use first element as default channel
      $.config.bustime_start,
    ]),
    // Cutter interacts with the database to perform cutting jobs
    if $.config.enabled.cutter then $.deployment("cutter",
    args=[
      "--base-dir", "/mnt",
      "--metrics-port", "80",
      "--name", $.config.localhost,
      "--tags", std.join(",", $.config.video_tags),
      $.db_connect,
      std.manifestJson($.config.cutter_config),
      "/etc/creds/cutter_creds.json"
    ],
    volumes=[
      {name:"credentials", secret: {secretName: "credentials"}}
    ],
    volumeMounts=[
      {mountPath: "/etc/creds", name: "credentials"},
    ]),
    // Sheetsync syncs database columns to the google docs sheet which is the primary operator interface
    if $.config.enabled.sheetsync then $.deployment("sheetsync",
    args=[
      "--allocate-ids",
      "--metrics-port", "80",
      $.config.db_connect,
      "/etc/creds/sheetsync_creds.json",
      $.config.edit_url,
      $.config.bustime_start,
      $.config.sheet_id
    ] + $.config.worksheets,
    volumes=[
      {name:"credentials", secret: {secretName: "credentials"}}
    ],
    volumeMounts=[
      {mountPath: "/etc/creds", name: "credentials"},
    ]),
    // playlist_manager adds videos to youtube playlists depending on tags
    if $.config.enabled.playlist_manager then $.deployment("playlist-manager",
    args=[
      "--metrics-port", "80",
      "--upload-location-allowlist", std.join(",", $.youtube_upload_locations),
      $.config.db_connect,
      "/etc/creds/cutter_creds.json"
    ] + [
        "%s=%s" % [playlist, std.join(",", $.playlists[playlist])]
        for playlist in std.objectFields($.playlists)
    ],
    volumes=[
      {name:"credentials", secret: {secretName: "credentials"}}
    ],
    volumeMounts=[
      {mountPath: "/etc/creds", name: "credentials"},
    ]),
    // chat_archiver records twitch chat messages and merges them with records from other nodes.
    if $.config.enabled.chat_archiver then $.deployment("chat-archiver",
    args=[
      $.config.chat_archiver.user,
      "/etc/creds/chat_token.txt",
      ] + $.config.clean_channels + [
      "--name", $.config.localhost,
      "--metrics-port", "80"
      ],
    volumes=[
      {name:"credentials", secret: {secretName: "credentials"}}
    ],
    volumeMounts=[
      {mountPath: "/etc/creds", name: "credentials"},
    ]),
    // Normally nginx would be responsible for proxying requests to different services,
    // but in k8s we can use Ingress to do that. However nginx is still needed to serve
    // static content - segments as well as thrimbletrimmer.
    if $.config.enabled.nginx then $.deployment("nginx", env=[
      {name: "THRIMBLETRIMMER", value: "true"},
      {name: "SEGMENTS", value: "/mnt"},
    ]),
    // postgres statefulset
    if $.config.enabled.postgres then $.statefulset("postgres", 
    args=if $.config.db_standby then ["/standby_setup.sh"] else [],
    env=[
      {name: "POSTGRES_USER", value: $.config.db_super_user},
      {name: "POSTGRES_PASSWORD", value: $.config.db_super_password},
      {name: "POSTGRES_DB", value: $.config.db_args.dbname},
      {name: "PGDATA", value: "/mnt/database"},
      {name: "WUBLOADER_USER", value: $.config.db_args.user},
      {name: "WUBLOADER_PASSWORD", value: $.config.db_args.password},
      {name: "REPLICATION_USER", value: $.config.db_replication_user},
      {name: "REPLICATION_PASSWORD", value: $.config.db_replication_password},
      {name: "READONLY_USER", value: $.config.db_readonly_user},
      {name: "READONLY_PASSWORD", value: $.config.db_readonly_password},
      {name: "MASTER_NODE", value: $.config.db_args.host},
    ]),
    // Services for all deployments
    if $.config.enabled.downloader then $.service("downloader"),
    if $.config.enabled.backfiller then $.service("backfiller"),
    if $.config.enabled.nginx then $.service("nginx"),
    if $.config.enabled.restreamer then $.service("restreamer"),
    if $.config.enabled.segment_coverage then $.service("segment-coverage"),
    if $.config.enabled.thrimshim then $.service("thrimshim"),
    if $.config.enabled.cutter then $.service("cutter"),
    if $.config.enabled.playlist_manager then $.service("playlist-manager"),
    if $.config.enabled.sheetsync then $.service("sheetsync"),
    if $.config.enabled.postgres then $.service("postgres"),
    if $.config.enabled.chat_archiver then $.service("chat-archiver"),
    // Secret for credentials
    if $.config.enabled.cutter || $.config.enabled.sheetsync || $.config.enabled.playlist_manager || $.config.enabled.chat_archiver then {
      apiVersion: "v1",
      kind: "Secret",
      metadata: {
        namespace: "wubloader",
        name: "credentials",
        labels: {app: "wubloader"}
      },
      type: "Opaque",
      stringData: {
        "cutter_creds.json": std.toString($.config.cutter_creds),
        "sheetsync_creds.json": std.toString($.config.sheetsync_creds),
        "chat_token.txt": $.config.chat_archiver.token,
        "downloader_token.txt": std.toString($.config.downloader_creds_file)
      },
    },
    // PV manifest for segments
    {
      apiVersion: "v1",
      kind: "PersistentVolume",
      metadata: {
        namespace: "wubloader",
        name: "segments",
        labels: {app: "wubloader"},
      },
      spec: {
        accessModes: ["ReadWriteMany"],
        capacity: {
          storage: $.config.nfs_capacity
        },
        mountOptions: $.config.nfs_mount_options,
        nfs: {
          server: $.config.nfs_server,
          path: $.config.nfs_path,
          readOnly: false
        },
        persistentVolumeReclaimPolicy: "Retain",
        volumeMode: "Filesystem"
      },
    },
    // PVC manifest for segments
    {
      apiVersion: "v1",
      kind: "PersistentVolumeClaim",
      metadata: {
        namespace: "wubloader",
        name: "segments",
        labels: {app: "wubloader"},
      },
      spec: {
        accessModes: ["ReadWriteMany"],
        resources: {
          requests: {
            storage: $.config.nfs_capacity
          },
        },
        storageClassName: "",
        volumeName: "segments"
      },
    },
    // Ingress to direct requests to the correct services.
    {
      kind: "Ingress",
      apiVersion: "networking.k8s.io/v1",
      metadata: {
        namespace: "wubloader",
        name: "wubloader",
        labels: {app: "wubloader"} + $.config.ingress_labels,
      },
      spec: {
        ingressClassName: $.config.ingress_class_name,
        rules: [
          {
            host: $.config.ingress_host,
            http: {
              // Helper functions for defining the path rules below
              local rule(name, path, type) = {
                path: path,
                pathType: type,
                backend: {
                  service: {
                    name: std.strReplace(name, "_", "-"),
                    port: {
                      number: 80
                    },
                  },
                },
              },
              local metric_rule(name) = rule(name, "/metrics/%s" % name, "Exact"),
              paths: [
                // Map /metrics/NAME to each service
                metric_rule("downloader"),
                metric_rule("backfiller"),
                metric_rule("restreamer"),
                metric_rule("segment_coverage"),
                metric_rule("thrimshim"),
                metric_rule("cutter"),
                metric_rule("sheetsync"),
                metric_rule("playlist_manager"),
                metric_rule("chat_archiver"),
                // Map /segments and /thrimbletrimmer to the static content nginx
                rule("nginx", "/segments", "Prefix"),
                rule("nginx", "/thrimbletrimmer", "Prefix"),
                // Map /thrimshim to the thrimshim service
                rule("thrimshim", "/thrimshim", "Prefix"),
                // Map everything else to restreamer
                rule("restreamer", "/", "Prefix"),
              ],
            },
          },
        ],
        [if $.config.ingress_tls then 'tls']: [
            {
                hosts: [
                    $.config.ingress_host,
                ],
                [if "ingress_secret_name" in $.config then 'secretName']: $.config.ingress_secret_name,
            },
        ],
      },
    },
  ],
}
