

all: .prometheus.uptodate .nginx.uptodate
.PHONY: all

.prometheus.uptodate: Dockerfile.prometheus prometheus.yml
	docker build -t wubloader_prometheus:latest -f Dockerfile.prometheus .
	touch "$@"

prometheus.yml: prometheus.jsonnet
	./generate-config
