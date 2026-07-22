# Workflow Log Config

This folder owns workflow-log domain service configuration. The broker-first
workflow-log server consumes workflow-log domain commands, consumes passive
`audit.events`, stores durable log entries, and publishes workflow-log domain
results only for command/reply requests.

Local keys:

- `WORKFLOW_LOG_SERVICE_NAME`: broker consumer group base name.
- `WORKFLOW_LOG_DOMAIN_COMMAND_TOPIC`: append/list command topic.
- `WORKFLOW_LOG_AUDIT_TOPIC`: observational audit event topic.
- `WORKFLOW_LOG_DB_PATH`: SQLite database file for durable workflow entries.
