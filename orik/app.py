"""Factoría de la app Flask."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from flask import Flask

from . import config
from .logging_setup import setup_logging
from .routes import bp


def create_app() -> Flask:
    setup_logging()

    templates_dir = Path(__file__).resolve().parent.parent / "templates"
    app = Flask(
        __name__,
        template_folder=str(templates_dir),
    )
    app.config.update(
        SECRET_KEY=config.FLASK_SECRET_KEY,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=config.SESSION_LIFETIME_DAYS),
        TEMPLATES_AUTO_RELOAD=config.FLASK_DEBUG,
        MAX_CONTENT_LENGTH=1 * 1024 * 1024,  # 1 MB de payload máximo
    )
    # UTF-8 en la salida JSON (Flask 3: se controla vía app.json)
    app.json.ensure_ascii = False
    app.register_blueprint(bp)
    return app
