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

    // For each component, whether to deploy that component.
    enabled: {
      downloader: true,
      restreamer: true,
      backfiller: true,
      cutter: false,            // TODO, docker-compose only for now
      sheetsync: false,         // TODO, docker-compose only for now
      thrimshim: true,
      segment_coverage: true,
      playlist_manager: false,  // TODO, docker-compose only for now
      nginx: true,
      postgres: false,          // TODO, docker-compose only for now
    },

    // Twitch channels to capture.
    // Channels suffixed with a '!' are considered "important" and will be retried more aggressively
    // and warned about if they're not currently streaming.
    channels: ["desertbus!", "db_chief", "db_high", "db_audio", "db_bus"],

    // Stream qualities to capture
    qualities: ["source", "480p"],

    // The node selector and hostPath to use. All pods must be on the same host
    // and use this hostpath in order to share the disk.
    node_selector: {},
    host_path: "/var/lib/wubloader",

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

    // Uncomment and give a secretName for ingress, if required for ingress TLS
    //ingress_secret_name: "wubloader-tls",

    // Additional metadata labels for Ingress (cert-manager, etc.) - adjust as needed for your setup
    ingress_labels: {},

    // Connection args for the database.
    // If database is defined in this config, host and port should be postgres:5432.
    db_args: {
      user: "vst",
      password: "dbfh2019", // don't use default in production. Must not contain ' or \ as these are not escaped.
      host: "postgres",
      port: 5432,
      dbname: "wubloader",
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
    cutter_config:: {
      desertbus: {type: "youtube"},
      unlisted: {type: "youtube", hidden: true, no_transcode_check: true},
    },
    default_location:: "desertbus",
    
    // The header to put at the front of video titles, eg. a video with a title
    // of "hello world" with title header "foo" becomes: "foo - hello world".
    title_header:: "DB2019",
    
    // The footer to put at the bottom of descriptions, in its own paragraph
    description_footer:: "Uploaded by the Desert Bus Video Strike Team",

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

  // This function generates deployments for each service, since they only differ slightly,
  // with only a different image, CLI args and possibly env vars.
  // The image name is derived from the component name
  // (eg. "downloader" is quay.io/ekimekim/wubloader-downloader)
  // so we only pass in name, args and env vars (with the latter two optional).
  // Optional kwargs work just like python.
  deployment(name, args=[], env=[]):: {
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
              image: "quay.io/ekimekim/wubloader-%s:%s" % [std.strReplace(name, "-", "_"), $.config.image_tag],
              args: args,
              volumeMounts: [{name: "data", mountPath: "/mnt"}],
              env: $.env_list + env, // main env list combined with any deployment-specific ones
            },
          ],
          volumes: [
            {
              name: "data",
              hostPath: {path: $.config.host_path},
            },
          ],
          nodeSelector: $.config.node_selector,
        },
      },
    },
  },

  // This function generates a Service object for each service, since they're basically identical.
  service(name):: {
    kind: "Service",
    apiVersion: "v1",
    metadata: {
      name: "wubloader-%s" % name,
      labels: {app: "wubloader", component: name},
    },
    spec: {
      selector: {app: "wubloader", component: name},
      ports: [{name: "http", port: 80, targetPort: 80}],
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
      "--qualities", std.join(",", $.config.qualities),
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
    // Normally nginx would be responsible for proxying requests to different services,
    // but in k8s we can use Ingress to do that. However nginx is still needed to serve
    // static content - segments as well as thrimbletrimmer.
    if $.config.enabled.nginx then $.deployment("nginx", env=[
      {name: "THRIMBLETRIMMER", value: "true"},
      {name: "SEGMENTS", value: "/mnt"},
    ]),
    // Services for all deployments
    if $.config.enabled.downloader then $.service("downloader"),
    if $.config.enabled.backfiller then $.service("backfiller"),
    if $.config.enabled.nginx then $.service("nginx"),
    if $.config.enabled.restreamer then $.service("restreamer"),
    if $.config.enabled.segment_coverage then $.service("segment-coverage"),
    if $.config.enabled.thrimshim then $.service("thrimshim"),
    // Ingress to direct requests to the correct services.
    {
      kind: "Ingress",
      apiVersion: "networking.k8s.io/v1beta1",
      metadata: {
        name: "wubloader",
        labels: {app: "wubloader"} + $.config.ingress_labels,
      },
      spec: {
        rules: [
          {
            host: $.config.ingress_host,
            http: {
              // Helper functions for defining the path rules below
              local rule(name, path, type) = {
                path: path,
                pathType: type,
                backend: {
                  serviceName: "wubloader-%s" % name,
                  servicePort: 80,
                },
              },
              local metric_rule(name) = rule(name, "/metrics/%s" % name, "Exact"),
              paths: [
                // Map /metrics/NAME to each service (except restreamer)
                metric_rule("downloader"),
                metric_rule("backfiller"),
                metric_rule("segment-coverage"),
                metric_rule("thrimshim"),
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
