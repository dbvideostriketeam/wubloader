local grafana = import "grafana.libsonnet";

local labels = {
  labels: 'instance=~"$instance", job=~"$job"',
};

grafana.dashboard({
  name: "OS Metrics",
  path: std.thisFile,
  uid: "aqxitqs1",
  refresh: "30s",

  templates: [
    {
      name: "instance",
      query: 'label_values(process_cpu_seconds_total, instance)',
    },
    {
      name: "job",
      query: 'label_values(process_cpu_seconds_total{instance=~"$instance"}, job)',
    },
  ],

  rows: [{
    panels: [
      [{
        name: "CPU usage",
        axis: {min: 0, format: grafana.formats.percent, label: "cores"},
        expressions: {
          "{{instance}} {{job}}": |||
            sum by (instance, job) (
              rate(process_cpu_seconds_total{%(labels)s}[2m])
            )
          ||| % labels,
        },
      }],
      [{
        name: "Memory (RSS)",
        axis: {min: 0, format: grafana.formats.bytes},
        expressions: {
          "{{instance}} {{job}}": |||
            process_resident_memory_bytes{%(labels)s}
          ||| % labels,
        },
      }],
      [{
        name: "Open file descriptors",
        axis: {min: 0, labels: "File descriptors"},
        expressions: {
          "{{instance}} {{job}}": |||
            process_open_fds{%(labels)s}
          ||| % labels,
        },
      }],
    ],
  }],

})
