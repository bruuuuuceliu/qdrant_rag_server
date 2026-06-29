"""Shared runtime logging setup."""

from __future__ import annotations

import logging
import os


def configure_logging(default_level: str = "INFO") -> None:
    level_name = os.environ.get("RAG_LOG_LEVEL", default_level).strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
