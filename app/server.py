"""Legacy FastAPI import path kept for compatibility."""

from app.bootstrap.http_app import app, create_app

__all__ = ["app", "create_app"]
