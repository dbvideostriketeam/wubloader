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
      thrimshim: true,          # storing editor inputs in postgres
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

    // clean version of the channel list without importance markers
    clean_channels:: [std.split(c, '!')[0] for c in $.channels],

    // Stream qualities to capture
    qualities: ["source", "480p"],

    // NFS settings for RWX (ReadWriteMany) volume for wubloader pods
    nfs_server: "nfs.example.com",            # server IP or hostname
    nfs_path: "/mnt/wubloader",               # path on server to mount
    nfs_capacity: "2T",                       # storage capacity to report to k8s

    // PVC template storage class for statefulsets
    sts_storage_class_name: "longhorn",

    // The local port within each container to bind the backdoor server on.
    // You can exec into the container and telnet to this port to get a python shell.
    backdoor_port: 1234,

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
      host: "wubloader-postgres",
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

    // The URL to write to the sheet for edit links, with {} being replaced by the id
    edit_url: "https://wubloader.example.com/thrimbletrimmer/edit.html?id={}",

    // The spreadsheet ID and worksheet names for sheetsync to act on
    sheet_id: "your_id_here",
    worksheets: ["Tech Test & Preshow"] + ["Day %d" % n for n in std.range(1,7)],
    
    // Fixed tags to add to all videos
    video_tags: ["DB15", "DB2021", "2021", "Desert Bus", "Desert Bus for Hope", "Child's Play Charity", "Child's Play", "Charity Fundraiser"],
    
    // A map from youtube playlist IDs to a list of tags.
    // Playlist manager will populate each playlist with all videos which have all those tags.
    // For example, tags ["Day 1", "Technical"] will populate the playlist with all Technical
    // youtube videos from Day 1.
    // Note that you can make an "all videos" playlist by specifying no tags (ie. []).
    playlists: {
      "YOUR-PLAYLIST-ID": ["some tag"],
    },

    // The timestamp corresponding to 00:00 in bustime
    bustime_start: "1970-01-01T00:00:00Z",

    // The timestamps to start/end segment coverage maps at.
    // Generally 1 day before and 7 days after bus start.
    coverage_start: "1969-12-31T00:00:00Z",
    coverage_end: "1970-01-07T00:00:00Z",

    // Max hours ago to backfill, ie. do not backfill for times before this many hours ago.
    // Set to null to disable.
    backfill_max_hours_ago: 24 * 30 * 6, // approx 6 months

    // Extra options to pass via environment variables,
    // eg. log level, disabling stack sampling.
    env: {
      // Uncomment this to set log level to debug
      // WUBLOADER_LOG_LEVEL: "DEBUG",
      // Uncomment this to enable stacksampling performance monitoring
      // WUBLOADER_ENABLE_STACKSAMPLER: "true",
    },

    // Config for cutter upload locations. See cutter docs for full detail.
    cutter_config: {
      desertbus: {type: "youtube", cut_type: "fast"},
    },
    default_location: "desertbus",

    // The header to put at the front of video titles, eg. a video with a title
    // of "hello world" with title header "foo" becomes: "foo - hello world".
    title_header: "DB2021",

    // The footer to put at the bottom of descriptions, in its own paragraph
    description_footer: "Uploaded by the Desert Bus Video Strike Team",

    // Chat archiver settings
    chat_archiver:: {
      // We currently only support archiving chat from one channel at once.
      // This defaults to the first channel in the $.channels list.
      channel: $.clean_channels[0],
      // Twitch user to log in as and path to oauth token
      user: "dbvideostriketeam",
      token: importstr "./chat_token.txt",
      // Whether to enable backfilling of chat archives to this node (if backfiller enabled)
      backfill: true,
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
  deployment(name, args=[], env=[], volumes=[], volumeMounts=[]):: {
    kind: "Deployment",
    apiVersion: "apps/v1",
    metadata: {
      name: "wubloader-%s" % name,
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
              image: "ghcr.io/dbvideostriketeam/wubloader-%s:%s" % [std.strReplace(name, "-", "_"), $.config.image_tag],
              args: args,
              volumeMounts: [{name: "data", mountPath: "/mnt"}] + volumeMounts,
              env: $.env_list + env, // main env list combined with any deployment-specific ones
            },
          ],
          volumes: [
            {
              name: "data",
              persistentVolumeClaim: {"claimName": "mnt-wubloader"},
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
      name: "wubloader-%s" % name,
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
      name: "wubloader-%s" % name,
      labels: {app: "wubloader", component: name},
    },
    spec: {
      replicas: 1,
      selector: {
        matchLabels: {app: "wubloader", component: name},
      },
      serviceName: "wubloader-%s" % name,
      template: {
        metadata: {
          labels: {app: "wubloader", component: name},
        },
        spec: {
          containers: [
            {
              name: name,
              image: "ghcr.io/dbvideostriketeam/wubloader-%s:%s" % [name, $.config.database_tag],
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
              persistentVolumeClaim: {"claimName": "mnt-wubloader"},
            },
          ],
        },
      },
      volumeClaimTemplates: [
        {
          metadata: {
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
    // The downloader watches the twitch stream and writes the HLS segments to disk
    if $.config.enabled.downloader then $.deployment("downloader", args=$.config.channels + [
      "--base-dir", "/mnt",
      "--qualities", std.join(",", $.config.qualities),
      "--backdoor-port", std.toString($.config.backdoor_port),
      "--metrics-port", "80",
    ]),
    // The restreamer is a http server that fields requests for checking what segments exist
    // and allows HLS streaming of segments from any requested timestamp
    if $.config.enabled.restreamer then $.deployment("restreamer", args=[
      "--base-dir", "/mnt",
      "--backdoor-port", std.toString($.config.backdoor_port),
      "--port", "80",
    ]),
    // The backfiller periodically compares what segments exist locally to what exists on
    // other nodes. If it finds ones it doesn't have, it downloads them.
    // It can talk to the database to discover other wubloader nodes, or be given a static list.
    if $.config.enabled.backfiller then $.deployment("backfiller", args=$.clean_channels + [
      "--base-dir", "/mnt",
      "--qualities", std.join(",", $.config.qualities + (if $.config.chat_archiver.backfill then ["chat"] else [])),
      "--static-nodes", std.join(",", $.config.peers),
      "--backdoor-port", std.toString($.config.backdoor_port),
      "--node-database", $.db_connect,
      "--localhost", $.config.localhost,
      "--metrics-port", "80",
    ] + (if $.config.backfill_max_hours_ago == null then [] else [
      "--start", std.toString($.config.backfill_max_hours_ago),
    ])),
    // Segment coverage is a monitoring helper that periodically scans available segments
    // and reports stats. It also creates a "coverage map" image to represent this info.
    // It puts this in the segment directory where nginx will serve it.
    if $.config.enabled.segment_coverage then $.deployment("segment-coverage", args=$.clean_channels + [
      "--base-dir", "/mnt",
      "--qualities", std.join(",", $.config.qualities),
      "--metrics-port", "80",
      "--first-hour", $.config.coverage_start,
      "--last-hour", $.config.coverage_end,
    ]),
    // Thrimshim acts as an interface between the thrimbletrimmer editor and the database
    // It is needed for thrimbletrimmer to be able to get unedited videos and submit edits
    if $.config.enabled.thrimshim then $.deployment("thrimshim", args=[
      "--port", "80",
      "--backdoor-port", std.toString($.config.backdoor_port),
      "--title-header", $.config.title_header,
      "--description-footer", $.config.description_footer,
      "--upload-locations", std.join(",", [$.config.default_location] + [
        location for location in std.objectFields($.config.cutter_config)
        if location != $.config.default_location
      ]),
      $.db_connect,
      $.clean_channels[0],  // use first element as default channel
      $.config.bustime_start,
    ]),
    // Cutter interacts with the database to perform cutting jobs
    if $.config.enabled.cutter then $.deployment("cutter",
    args=[
      "--base-dir", "/mnt",
      "--backdoor-port", std.toString($.config.backdoor_port),
      "--metrics-port", "80",
      "--name", $.config.localhost,
      "--tags", std.join(",", $.config.video_tags),
      $.db_connect,
      std.manifestJson($.config.cutter_config),
      "/etc/creds/cutter_creds.json"
    ],
    volumes=[
      {name:"wubloader-creds", secret: {secretName: "wubloader-creds"}}
    ],
    volumeMounts=[
      {mountPath: "/etc/creds", name: "wubloader-creds"},
    ]),
    // Sheetsync syncs database columns to the google docs sheet which is the primary operator interface
    if $.config.enabled.sheetsync then $.deployment("sheetsync",
    args=[
      "--allocate-ids",
      "--backdoor-port", std.toString($.config.backdoor_port),
      "--metrics-port", "80",
      $.config.db_connect,
      "/etc/creds/sheetsync_creds.json",
      $.config.edit_url,
      $.config.bustime_start,
      $.config.sheet_id
    ] + $.config.worksheets,
    volumes=[
      {name:"wubloader-creds", secret: {secretName: "wubloader-creds"}}
    ],
    volumeMounts=[
      {mountPath: "/etc/creds", name: "wubloader-creds"},
    ]),
    // playlist_manager adds videos to youtube playlists depending on tags
    if $.config.enabled.playlist_manager then $.deployment("playlist-manager",
    args=[
      "--backdoor-port", std.toString($.config.backdoor_port),
      "--metrics-port", "80",
      "--upload-location-allowlist", std.join(",", $.youtube_upload_locations),
      $.config.db_connect,
      "/etc/creds/cutter_creds.json"
    ] + [
        "%s=%s" % [playlist, std.join(",", $.playlists[playlist])]
        for playlist in std.objectFields($.playlists)
    ],
    volumes=[
      {name:"wubloader-creds", secret: {secretName: "wubloader-creds"}}
    ],
    volumeMounts=[
      {mountPath: "/etc/creds", name: "wubloader-creds"},
    ]),
    // chat_archiver records twitch chat messages and merges them with records from other nodes.
    if $.config.enabled.chat_archiver then $.deployment("chat-archiver",
    args=[
      $.config.chat_archiver.channel,
      $.config.chat_archiver.user,
      "/etc/creds/chat_token.txt",
      "--name", $.config.localhost
    ],
    volumes=[
      {name:"wubloader-creds", secret: {secretName: "wubloader-creds"}}
    ],
    volumeMounts=[
      {mountPath: "/etc/creds", name: "wubloader-creds"},
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
    // Secret for cutter_creds_file and sheetsync_creds_file
    if $.config.enabled.cutter || $.config.enabled.sheetsync || $.config.enabled.playlist_manager || $.config.enabled.chat_archiver then {
      apiVersion: "v1",
      kind: "Secret",
      metadata: {
        name: "wubloader-creds",
        labels: {app: "wubloader"}
      },
      type: "Opaque",
      stringData: {
        "cutter_creds.json": std.toString($.config.cutter_creds),
        "sheetsync_creds.json": std.toString($.config.sheetsync_creds),
        "chat_token.txt": $.config.chat_archiver.token
      },
    },
    // PV manifest for segments
    {
      apiVersion: "v1",
      kind: "PersistentVolume",
      metadata: {
        name: "mnt-wubloader",
        labels: {app: "wubloader"},
      },
      spec: {
        accessModes: ["ReadWriteMany"],
        capacity: {
          storage: $.config.nfs_capacity
        },
        mountOptions: ["fsc"],
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
        name: "mnt-wubloader",
        labels: {app: "wubloader"},
      },
      spec: {
        accessModes: ["ReadWriteMany"],
        resources: {
          requests: {
            storage: $.config.nfs_capacity
          },
        },
        volumeName: "mnt-wubloader"
      },
    },
    // Ingress to direct requests to the correct services.
    {
      kind: "Ingress",
      apiVersion: "networking.k8s.io/v1",
      metadata: {
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
                    name: "wubloader-%s" % std.strReplace(name, "_", "-"),
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
