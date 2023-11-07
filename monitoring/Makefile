
REQUIRED_FILES := grafana/tls.key grafana/tls.crt

all: .prometheus.uptodate $(REQUIRED_FILES)
.PHONY: all

.prometheus.uptodate: Dockerfile.prometheus prometheus.yml
	docker build -t wubloader_prometheus:latest -f Dockerfile.prometheus .
	touch "$@"

prometheus.yml: prometheus.jsonnet
	./generate-config

$(REQUIRED_FILES):
	echo "Missing required file: $@" >&2 && exit 1
