local hosts = {
  // name: "host:port"
};
local services = [
  "restreamer",
  "downloader",
  "backfiller",
  "cutter",
  "thrimshim",
  "sheetsync",
  "segment_coverage",
];

{
  global: {
    evaluation_interval: "15s",
    scrape_interval: "15s",
  },
  scrape_configs: [
    {
      job_name: "prometheus",
      static_configs: [
        {targets: ["localhost:9090"], labels: {instance: "prometheus"}}
      ],
    },
  ] + [
    {
      job_name: service,
      metrics_path: "/metrics/%s" % service,
      static_configs: [
        {
          targets: [hosts[host]],
          labels: {instance: host},
        } for host in std.objectFields(hosts)
      ],
    }
    for service in services
  ],
}
