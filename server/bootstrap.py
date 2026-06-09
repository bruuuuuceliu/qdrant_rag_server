"""Compatibility bootstrap imports for project-service startup wiring."""

from configs import AppSettings
from project_service.server.app import AppContext, create_app, serve_forever

__all__ = ["AppContext", "AppSettings", "create_app", "serve_forever"]
