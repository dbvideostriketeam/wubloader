local grafana = import "grafana.libsonnet";

// Map from service to regex of matching roles.
// Role explanations:
//  replica: Just downloads and replicates segments
//  local_edit: Also runs a local thrimbletrimmer for doing local cuts
//  edit: Also runs cutter for doing uploads
//  leader: Also runs things that only run in one place, eg. sheetsync
local roles_for_service = {
  "restreamer": ".*",
  "downloader": ".*",
  "backfiller": ".*",
  "segment_coverage": ".*",
  "thrimshim": "leader|edit|local_edit",
  "cutter": "leader|edit",
  "sheetsync": "leader",
};

// List of services, to impart ordering
local services = [
  "restreamer",
  "downloader",
  "backfiller",
  "segment_coverage",
  "thrimshim",
  "cutter",
  "sheetsync",
];

local service_status_table = {
  local refId(n) = std.char(std.codepoint('A') + n),
  type: "table",
  targets: [
    {
      expr: 'sum(up{service="%s", role=~"%s"}) by (instance)' % [services[i], roles_for_service[services[i]]],
      intervalFactor: 1,
      format: "table",
      refId: refId(i),
      legendFormat: "",
      instant: true,
    }
    for i in std.range(0, std.length(services) - 1)
  ],
  styles: [
    // hidden cols
    {
      unit: "short",
      type: "hidden",
      alias: "",
      decimals: 2,
      colors: [
        "rgba(245, 54, 54, 0.9)",
        "rgba(237, 129, 40, 0.89)",
        "rgba(50, 172, 45, 0.97)",
      ],
      colorMode: null,
      pattern: name,
      dateFormat: "YYYY-MM-DD HH:mm:ss",
      thresholds: [],
      mappingType: 1,
    }
    for name in ["__name__", "service", "Time"]
  ] + [
    // service cols
    {
      unit: "short",
      type: "string",
      alias: services[i],
      decimals: 2,
      colors: [
        "rgba(245, 54, 54, 0.9)",
        "rgba(237, 129, 40, 0.89)",
        "rgba(50, 172, 45, 0.97)",
      ],
      colorMode: "cell",
      pattern: "Value #%s" % refId(i),
      dateFormat: "YYYY-MM-DD HH:mm:ss",
      thresholds: [
        "0.5",
        "0.5",
      ],
      mappingType: 1,
      valueMaps: [
        {
          value: "0",
          text: "DOWN",
        },
        {
          value: "1",
          text: "UP",
        },
      ],
    } for i in std.range(0, std.length(services) - 1)
  ],
  transform: "table",
  pageSize: null,
  showHeader: true,
  columns: [],
  scroll: true,
  fontSize: "100%",
  sort: {col: 1, desc: false}, // sort by instance
  links: [],
};

local labels = {
  labels: 'instance=~"$instance"'
};

grafana.dashboard({
  name: "Overview",
  uid: "rjd405mn",
  refresh: "30s",

  templates: [
    {
      name: "instance",
      query: 'label_values(up, instance)'
    },
  ],

  rows: [

    {
      panels: [
        // First row - immediate status heads-up
        [
          {
            name: "Service Status by Node",
            span: 2 * grafana.span.third,
            custom: service_status_table,
          },
          {
            name: "Error log rate",
            axis: {min: 0, label: "logs / sec"},
            display: "bars",
            expressions: {
              "{{instance}} {{service}} {{level}}({{module}}:{{function}})": |||
                sum(irate(log_count_total{level!="INFO", %(labels)s}[2m])) by (instance, service, level, module, function) > 0
              ||| % labels,
            },
          },
        ],
        // Second row - core "business" metrics
        [
          {
            name: "Segments downloaded",
            axis: {min: 0, label: "segments / sec"},
            expressions: {
              "{{channel}}({{quality}}) live capture":
                'sum(rate(segments_downloaded_total{%(labels)s}[2m])) by (channel, quality)' % labels,
              "{{channel}}({{quality}}) backfilled":
                'sum(rate(segments_backfilled_total{%(labels)s}[2m])) by (channel, quality)' % labels,
            },
          },
          {
            name: "Successful requests by endpoint",
            axis: {min: 0, label: "requests / sec"},
            expressions: {
              "{{method}} {{endpoint}}":
                'sum(rate(http_request_latency_all_count{status="200", %(labels)s}[2m])) by (endpoint, method)' % labels,
            },
          },
          {
            name: "Database events by state",
            axis: {min: 0, label: "events"},
            stack: true,
            tooltip: "Does not include UNEDITED or DONE events",
            expressions: {
              "{{state}}": |||
                sum(event_counts{state!="UNEDITED", state!="DONE", %(labels)s}) by (state)
              ||| % labels,
            },
          },
        ],
        // Third row - process-level health
        [
          {
            name: "CPU usage",
            axis: {min: 0, label: "cores", format: grafana.formats.percent},
            expressions: {
              "{{instance}} {{service}}": |||
                sum by (instance, service) (
                  rate(process_cpu_seconds_total{%(labels)s}[2m])
                )
              ||| % labels,
            },
          },
          {
            name: "Memory usage (RSS)",
            axis: {min: 0, format: grafana.formats.bytes},
            expressions: {
              "{{instance}} {{service}}": "process_resident_memory_bytes{%(labels)s}" % labels,
            },
          },
          {
            name: "Process restarts",
            axis: {min: 0, label: "restarts within last minute"},
            tooltip: "Multiple restarts within 15sec will be missed, and only counted as one.",
            expressions: {
              "{{instance}} {{service}}": "changes(process_start_time_seconds{%(labels)s}[1m])" % labels,
            },
          },
        ],
      ],
    },

    {
      name: "Downloader",
      panels: [
        {
          name: "Segments downloaded by node",
          axis: {min: 0, label: "segments / sec"},
          expressions: {
            "{{instance}} {{channel}}({{quality}})":
              'sum(rate(segments_downloaded_total{%(labels)s}[2m])) by (instance, channel, quality)' % labels,
          },
        },
        {
          name: "Downloader stream delay by node",
          tooltip: "Time between the latest downloaded segment's timestamp and current time",
          axis: {min: 0, format: grafana.formats.time},
          expressions: {
            "{{instance}} {{channel}}({{quality}})":
              // Ignore series where we're no longer fetching segments,
              // as they just show that it's been a long time since the last segment.
              |||
                time() - max(latest_segment{%(labels)s}) by (instance, channel, quality)
                and sum(irate(segments_downloaded_total{%(labels)s}[2m])) by (instance, channel, quality) > 0
              ||| % labels,
          },
        },
      ],
    },

    {
      name: "Backfiller",
      panels: [
        {
          name: "Backfill by node pair",
          axis: {min: 0, label: "segments / sec"},
          expressions: {
            "{{remote}} -> {{instance}}":
              'sum(rate(segments_backfilled_total{%(labels)s}[2m])) by (remote, instance)' % labels,
          },
        },
      ],
    },

  ],

})
