# Broker Config

This folder owns message-broker configuration for the independent broker node.

Redpanda is the runtime broker target for both local and production. Local
development should point services at a locally running Redpanda broker rather
than in-memory, file-based, or SQLite queue substitutes.

## Bootstrap

Use `examples/local/run-all.sh --infra-only` to start or verify local Redpanda
and Redis, bootstrap canonical topics, and run readiness checks without service
processes. For a direct live smoke after that gate, run:

```bash
RAG_LIVE_INFRA=1 pytest -m live_infra tests/integration/test_live_infra_smoke.py -q
```

## Health

Broker readiness includes:

- `ok`
- `topics`
- `bootstrap_servers`
- `topic_prefix`
- `required_topic_count`
- `missing_topics`
- optional `lag` or `lag_error`

Lag targets are optional and use `BROKER_LAG_TARGETS`:

```text
group_id:topic,topic;group_id:topic
```

Example local broker-first groups are documented in `local.env.example`.

Retries, leases, attempt counts, backoff, and dead-letter decisions are outside
the broker boundary. The task manager owns those semantics; the broker owns
transport, deterministic topic bootstrap, health, and optional lag visibility.
