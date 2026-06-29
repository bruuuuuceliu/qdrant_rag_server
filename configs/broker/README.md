# Broker Config

This folder owns message-broker configuration for the independent broker node.

Redpanda is the default runtime broker target for both local and production.
The runtime adapter uses the Kafka protocol, so local development can also run
against Apache Kafka when compatibility testing is useful. In both cases,
services should point at a locally running Docker broker rather than in-memory,
file-based, or SQLite queue substitutes.

Supported local Docker brokers:

- `BROKER_TYPE=redpanda`, the default, starts `redpanda-rag-local`.
- `BROKER_TYPE=kafka`, or `examples/local/run-all.sh --broker kafka`, starts
  `kafka-rag-local` from the official `apache/kafka` image.

## Bootstrap

Use `examples/local/run-all.sh --infra-only` to start or verify the selected
local broker and Redis, bootstrap canonical topics, and run readiness checks
without service processes. For a direct live smoke after that gate, run:

```bash
RAG_LIVE_INFRA=1 pytest -m live_infra tests/integration/test_live_infra_smoke.py -q
```

To run the same smoke against Apache Kafka:

```bash
examples/local/run-all.sh --reset --infra-only --broker kafka
RAG_LIVE_INFRA=1 BROKER_TYPE=kafka pytest -m live_infra tests/integration/test_live_infra_smoke.py -q
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
