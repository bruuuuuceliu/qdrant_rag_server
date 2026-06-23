# Config Profile Variants

Status: accepted.

## Requirement

Keep all configuration code, profile defaults, and env examples under
`./configs`, while supporting local and production variants that can be selected
by profile or promoted into the active `config.py` during deployment.

The active runtime import remains `configs.config` so application code does not
need to know which profile is selected. Profile-specific modules provide both
default values and the same public loader API as the active config file, so a
deployment can copy `config_local.py` or `config_production.py` to
`configs/config.py` without breaking imports. Env files and process environment
variables remain the final override layer for secrets and deployment-specific
values.

## Acceptance Criteria

- Add explicit Python profile modules under `configs/` such as
  `config_local.py` and `config_production.py`.
- `configs/config.py` can load profile defaults from those modules.
- Profile `.env.example` files continue to live under `configs/`.
- Load order is deterministic:
  profile Python defaults, then selected profile env file, then component env
  files, then process environment variables.
- Existing callers can keep using `from configs import load_settings`.
- Local testing defaults to the local profile.
- Production can either pass `profile="production"` / `RAG_CONFIG_PROFILE`, or
  copy the production profile module to `configs/config.py` if deployment policy
  requires a single active config file.
- Copied profile modules expose `AppSettings`, `load_settings`, and config
  helper functions used by component config modules.
- Tests prove local defaults, production defaults, profile env loading, and env
  override precedence, plus active-compatible profile modules.
- Unknown profile names are rejected instead of silently falling back to empty
  defaults.
- Production deployment validation is available without starting services.

## Structure Design

```text
configs/base.py
  shared AppSettings dataclass, loader implementation, env parser, and helpers

configs/config.py
  stable active entrypoint that defaults to the local profile unless profile
  selection overrides it

configs/config_local.py
  DEFAULT_ENV values and an active-compatible loader defaulting to local

configs/config_production.py
  DEFAULT_ENV values and an active-compatible loader defaulting to production

configs/config_testing.py
  test-safe in-memory defaults

configs/validation.py
  structured validation checks for production readiness

configs/local.env.example
configs/production.env.example
  profile env examples
```

## Class Design

- `AppSettings` remains the single typed runtime settings dataclass.
- `configs.base.AppSettings` owns the canonical fields and `from_env(...)`
  helper for the stable active entrypoint.
- `configs.config_local.AppSettings` and
  `configs.config_production.AppSettings` subclass the base dataclass only to
  pin `from_env(...)` to their promoted profile default.
- Profile modules expose the same parsing helpers as `configs.config` for
  component config modules that import `get_bool_value`, `get_int_value`,
  `get_float_value`, `get_optional_value`, or `get_value`.

## Implementation Design

1. Add `DEFAULT_ENV` dictionaries to `config_local.py` and
   `config_production.py`.
2. Move shared loader implementation to `configs/base.py`.
3. Keep `configs/config.py` as the stable active entrypoint.
4. Make `config_local.py` and `config_production.py` active-compatible
   entrypoints that pin their profile when copied to `config.py`.
5. Add `RAG_CONFIG_PROFILE` support when no explicit profile is passed through
   the stable active entrypoint.
6. Preserve process environment override precedence.
7. Add tests for profile selection, override order, and copied-profile API
   compatibility.
8. Add validation helpers for URLs, paths, modes, profile names, and
   production-only requirements.
9. Update docs/progress after verification.

## Review Notes

- Secrets do not belong in profile Python files or committed env examples.
- Copying `config_production.py` over `config.py` is supported as a deployment
  convention because profile files export the same public API. Selecting a
  profile remains simpler for development because it avoids changing the active
  file in the working tree.
- Validation is intentionally side-effect free: it checks values but does not
  connect to services, create directories, or write files.
