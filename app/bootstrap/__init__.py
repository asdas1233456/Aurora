"""Bootstrap entrypoints for Aurora application startup."""

from app.bootstrap.http_app import app, create_app

__all__ = ["app", "create_app"]
