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
    "downloader",
    "restreamer",
    "backfiller",
    "chat_archiver",
    "segment_coverage",
  ],
  local_edit: self.replica + ["thrimshim"],
  edit: self.local_edit + ["cutter"],
  backup: self.edit + [
    "postgres_exporter",
    "buscribe_api",
    "pubbot",
    "prizebot",
    "tootbot",
    "blogbot",
    "twitch_stats",
  ],
  leader: self.backup + [
    "sheetsync",
    "playlist_manager",
    "buscribe",
    "bus_analyzer",
    "schedulebot",
    "twitchbot",
    "youtubebot",
  ],
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
      local service = services[service_index];
      {
        local hosts = hosts_by_scheme[scheme],
        job_name: "%s-%s" % [scheme, service],
        metrics_path: "/metrics/%s" % service,
        scheme: scheme,
        fallback_scrape_protocol: "PrometheusText0.0.4",
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
              // The index gives us a natural ordering when showing services in a table
              service_index: service_index,
            },
          } for host in std.objectFields(hosts)
          if std.count(services_by_role[hosts[host][1]], service) > 0
        ],
      }
      for service_index in std.range(0, std.length(services)-1)
    ]
    for scheme in std.objectFields(hosts_by_scheme)
  ]),
}
