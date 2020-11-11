local hosts_by_scheme = {
  http: {
    // name: ["host:port", role]
    // See overview.jsonnet for role explanations.
    mynode: ["localhost:8080", "replica"]
  },
  https: {
  },
};
local services_by_role = {
  replica: [
    "restreamer",
    "downloader",
    "backfiller",
    "segment_coverage",
  ],
  local_edit: self.replica + ["thrimshim"],
  edit: self.local_edit + ["cutter"],
  leader: self.edit + ["sheetsync", "playlist_manager"],
};
local services = services_by_role.leader;

{
  global: {
    evaluation_interval: "15s",
    scrape_interval: "15s",
  },
  scrape_configs: [
    {
      job_name: "prometheus",
      static_configs: [
        {targets: ["localhost:9090"], labels: {instance: "prometheus", service: "prometheus"}},
      ],
    },
  ] + std.flattenArrays([
    [
      {
        local hosts = hosts_by_scheme[scheme],
        job_name: "%s-%s" % [scheme, service],
        metrics_path: "/metrics/%s" % service,
        scheme: scheme,
        static_configs: [
          {
            local target = hosts[host][0],
            local role = hosts[host][1],
            targets: [target],
            labels: {
              instance: host,
              target: target,
              url: "%s://%s" % [scheme, target],
              role: role,
              service: service,
            },
          } for host in std.objectFields(hosts)
          if std.count(services_by_role[hosts[host][1]], service) > 0
        ],
      }
      for service in services
    ]
    for scheme in std.objectFields(hosts_by_scheme)
  ]),
}
