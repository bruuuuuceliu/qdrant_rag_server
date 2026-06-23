"""Active application configuration entrypoint.

By default this entrypoint selects the local profile, unless
``RAG_CONFIG_PROFILE`` or an explicit ``profile=`` value chooses another
profile. Deployment systems that require a single active file may promote
``config_local.py`` or ``config_production.py`` over this file; those profile
files expose the same public loader API.
"""

from __future__ import annotations

from configs.base import (
    AppSettings,
    get_bool_value,
    get_float_value,
    get_int_value,
    get_optional_value,
    get_positive_int_value,
    get_value,
    load_settings_from_defaults,
    load_settings,
    profile_defaults,
    profile_env,
    profile_name_from_env,
    read_env_file,
)

__all__ = [
    "AppSettings",
    "get_bool_value",
    "get_float_value",
    "get_int_value",
    "get_optional_value",
    "get_positive_int_value",
    "get_value",
    "load_settings_from_defaults",
    "load_settings",
    "profile_defaults",
    "profile_env",
    "profile_name_from_env",
    "read_env_file",
]
