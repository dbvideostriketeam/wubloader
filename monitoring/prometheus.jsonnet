local hosts = [
  "toodles.videostrike.team:1337",
  "http://136.24.9.73:20088",
  "wubloader.codegunner.com",
];
local services = [
  "restreamer",
  "downloader",
  "backfiller",
  "cutter",
  "thrimshim",
  "sheetsync",
];

{
  global: {
    evaluation_interval: "15s",
    scrape_interval: "15s",
  },
  scrape_configs: [
    {job_name: "prometheus", static_configs: [{targets: ["localhost:9090"]}]},
  ] + [
    {
      job_name: service,
      metrics_path: "/metrics/%s" % service,
      static_configs: [{
        targets: hosts,
      }],
    }
    for service in services
  ],
}
