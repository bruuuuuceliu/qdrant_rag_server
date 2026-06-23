# Local Runner Retrieval HTTP Mode Guard

Status: accepted.

## Requirement

Prevent the local runner from advertising or starting an unsupported composition
where manager retrieval execution is remote HTTP but project planning is remote
through the compatibility project gRPC client.

Manager HTTP retrieval mode currently still needs local project planning because
project config and scope APIs have not been extracted. The local runner should
allow `--external-retrieval-http` only while manager project client mode remains
local, and should fail early with a clear message for incompatible combinations.

## Acceptance Criteria

- `--external-retrieval-http` starts the retrieval HTTP server and switches
  manager retrieval mode to HTTP when project planning stays local.
- `--external-retrieval-http --external-project-service` fails before starting
  services with a clear project-planning message.
- `--external-retrieval-http --split-services` fails for the same reason,
  because `--split-services` implies external project service.
- Local runner docs show the supported retrieval HTTP command separately from
  full split-service mode.
- Tests check the shell script text for the guard and supported example.

## Structure Design

```text
examples/local/run-all.sh
  validate_mode_combination(...)

examples/local/README.md
  supported retrieval HTTP command

tests/test_retrieval_http_worker.py
  runner guard text checks
```

## Implementation Design

1. Add a validation function after argument parsing and env loading.
2. If `EXTERNAL_RETRIEVAL_HTTP=1` and `EXTERNAL_PROJECT_SERVICE=1`, print a
   clear error explaining that HTTP retrieval mode still needs local project
   planning.
3. Keep `--external-retrieval-http` supported with embedded project planning.
4. Update README examples and focused runner-reference tests.

## Review Notes

- This is intentionally conservative. It prevents a known bad local mode until
  project config/scope APIs make remote project planning possible.
- The retrieval HTTP server itself remains usable for manager local project
  planning and physical retrieval execution.
