# Task Service Config

This folder owns task-service execution/orchestration configuration.

Local keys:

- `TASK_SERVICE_NAME`: broker consumer group base name.
- `TASK_SERVICE_TASK_REQUEST_TOPIC`: task-manager request topic.
- `TASK_SERVICE_PROJECT_PLAN_REQUEST_TOPIC`: project planning request topic.
- `TASK_SERVICE_PROJECT_PLAN_RESULT_TOPIC`: project planning result topic.
- `TASK_SERVICE_TASK_EVENT_TOPIC`: lifecycle event topic.
- `TASK_SERVICE_TASK_RESULT_TOPIC`: final result topic.
- `TASK_SERVICE_DEAD_LETTER_TOPIC`: terminal helper failure topic.
- `TASK_SERVICE_STATE_DB_PATH`: SQLite execution-state database path.
- `TASK_SERVICE_MAX_ATTEMPTS`: max helper attempts before terminal failure.
- `TASK_SERVICE_HELPER_LEASE_SECONDS`: helper dispatch lease duration before recovery treats the step as expired.
- `TASK_SERVICE_RETRY_BACKOFF_SECONDS`: delay before retryable helper failures are redispatched; `0` keeps immediate retries.
- `TASK_SERVICE_RECOVERY_ENABLED`: enables the task-service DB recovery loop.
- `TASK_SERVICE_RECOVERY_POLL_SECONDS`: recovery loop sleep interval.
- `TASK_SERVICE_RECOVERY_BATCH_SIZE`: max due helper steps claimed per recovery pass.
