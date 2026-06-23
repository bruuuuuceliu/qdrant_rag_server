# Broker Config

This folder owns message-broker configuration for the independent broker node.

Redpanda is the runtime broker target for both local and production. Local
development should point services at a locally running Redpanda broker rather
than in-memory, file-based, or SQLite queue substitutes.

Retries, leases, attempt counts, backoff, and dead-letter topics are out of
scope for the current broker phase.
