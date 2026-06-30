# Configuration Profiles

All configuration code, profile defaults, and env examples live under
`./configs`.

Service-specific configuration must be separated by service or node under this
folder. The target layout includes manager, project, ingestion, retrieval,
workflow log, broker, Redis task-status, storage, and SQLite/database-node
config folders. Shared profile defaults may exist only for deployment-wide
values; service-specific settings should stay in the owning service or node
folder.

Runtime code imports the stable active loader:

```python
from configs import load_settings
```

`configs/config.py` is the active loader. Shared loader code lives in
`configs/base.py`; profile files wrap that loader with profile-specific
defaults. Values load in this order:

1. Python profile defaults from `configs/config_<profile>.py`
2. Profile env file such as `configs/local.env` or `configs/production.env`
3. Component env files passed by the caller
4. Process environment variables

Later layers override earlier layers. Secrets should be provided by uncommitted
env files or process environment variables, not by committed Python defaults.

## Profiles

Available active-compatible profile modules:

- `configs/config_local.py`
- `configs/config_production.py`
- `configs/config_testing.py` for tests and in-memory local checks

Select a profile explicitly:

```python
settings = load_settings(profile="production")
```

Or by environment:

```bash
RAG_CONFIG_PROFILE=production python -m manager_service.worker
```

Local remains the default when no profile is selected.

## Env Files

Committed env examples:

- `configs/local.env.example`
- `configs/production.env.example`
- component examples under `configs/*/*.env.example`

## Service Folder Status

Current folders include manager, project, ingestion, retrieval, workflow log,
memory, storage, Qdrant, embeddings, generation, broker, Redis task-status, and
SQLite/database node settings. Runtime composition uses Redpanda-compatible
broker settings, Redis task status, and SQLite database-node settings.

For local testing, copy examples to untracked `.env` files when needed, then
adjust values and secrets there.

## Deployment Copy Workflow

Some deployments prefer a single active config file. That convention still
works: copy the desired profile module over `configs/config.py` during image or
release preparation. For example:

```bash
cp configs/config_local.py configs/config.py
cp configs/local.env.example configs/local.env
```

For production deployment preparation:

```bash
cp configs/config_production.py configs/config.py
cp configs/production.env.example configs/production.env
```

The profile modules expose the same `AppSettings`, `load_settings`, and helper
functions as `configs/config.py`, so runtime imports continue to work after the
copy. The safer default during development is to keep `configs/config.py` as the
stable loader and select profiles with `RAG_CONFIG_PROFILE`.

## Validation

Validate loaded settings before production startup or deployment checks:

```python
from configs import load_settings, validate_settings_or_raise

settings = load_settings(profile="production")
validate_settings_or_raise(settings, profile="production")
```

Validation checks profile names, Qdrant URLs/hosts, URL syntax, absolute
filesystem paths, object storage mode, placement counts, and production-only
secret/path requirements. It does not open network connections or create files.
