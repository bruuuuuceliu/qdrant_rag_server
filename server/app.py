"""Compatibility shim for project-service application bootstrap."""

from project_service.server.app import (
    AppContext,
    create_app,
    main,
    serve_forever,
)
from configs import AppSettings, load_settings

__all__ = [
    "AppContext",
    "AppSettings",
    "create_app",
    "load_settings",
    "main",
    "serve_forever",
]


if __name__ == "__main__":
    main()
