# Redis Task Status Config

This folder owns configuration for the Redis task-status node.

Redis stores task status by `task_id`. The task manager is the writer, and the
manager reads Redis directly for client status checks. Completed task records
must use TTL so Redis does not grow without bound.

Redis must not be used as the message broker. Redpanda remains the broker for
service-to-service messages.
