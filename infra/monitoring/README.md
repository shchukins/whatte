# Monitoring

Human Engine monitoring is currently centered on the observability stack in [observability](/srv/human-engine/infra/monitoring/observability).

Current status:

- observability stack exists
- stack is operational / optional
- Grafana is available in repo config but should be treated as "currently not primary" infrastructure rather than product-critical runtime

Primary files:

- [observability/docker-compose.yml](/srv/human-engine/infra/monitoring/observability/docker-compose.yml)
- [observability/loki-config.yaml](/srv/human-engine/infra/monitoring/observability/loki-config.yaml)
- [observability/promtail-config.yaml](/srv/human-engine/infra/monitoring/observability/promtail-config.yaml)
- [observability/grafana/provisioning/datasources/loki.yaml](/srv/human-engine/infra/monitoring/observability/grafana/provisioning/datasources/loki.yaml)

Data directories on host:

- `/data/observability/loki`
- `/data/observability/grafana`
- `/data/observability/promtail`

Run:

```bash
docker compose -f /srv/human-engine/infra/monitoring/observability/docker-compose.yml up -d
```

Basic checks:

```bash
docker compose -f /srv/human-engine/infra/monitoring/observability/docker-compose.yml ps
curl http://localhost:3100/ready
docker logs human-engine-backend --tail 20
```

Grafana / Loki / Promtail summary:

- Loki listens on `http://localhost:3100`
- Grafana listens on `http://localhost:3001`
- Promtail tails Docker JSON logs and pushes them to Loki

The detailed stack-specific instructions remain in [observability/README.md](/srv/human-engine/infra/monitoring/observability/README.md).
