local hosts = {
  // name: ["host:port", role]
  // See overview.jsonnet for role explanations.
  mynode: ["localhost:8080", "replica"]
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
          targets: [hosts[host][0]],
          labels: {
            instance: host,
            role: hosts[host][1],
          },
        } for host in std.objectFields(hosts)
      ],
    }
    for service in services
  ],
}
