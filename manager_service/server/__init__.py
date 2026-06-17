"""Manager service server package."""

__all__ = ["ManagerAppContext", "create_app", "main", "serve_forever"]


def __getattr__(name: str):
    if name in __all__:
        from manager_service.server import app

        return getattr(app, name)
    raise AttributeError(name)
