"""Flask + Flask-SocketIO application factory."""

from __future__ import annotations

import threading
from typing import Optional, Tuple

from flask import Flask
from flask_socketio import SocketIO

from app.config import AppConfig
from app.core.db import Database


def create_app(
    cfg: AppConfig,
    db: Database,
    *,
    camera=None,
    camera_lock: Optional[threading.Lock] = None,
    async_mode: Optional[str] = None,
) -> Tuple[Flask, SocketIO]:
    """Build the Flask app and SocketIO server.

    ``async_mode`` may be set to ``"threading"`` for testing or when eventlet
    is unavailable.
    """
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.config["SECRET_KEY"] = cfg.web.secret_key
    app.config["WASTE_CONFIG"] = cfg
    app.config["WASTE_DB"] = db
    app.config["WASTE_CAMERA"] = camera
    app.config["WASTE_CAMERA_LOCK"] = camera_lock or threading.Lock()

    socketio = SocketIO(app, async_mode=async_mode)

    # Register routes (import here to avoid circular imports)
    from . import routes  # noqa: WPS433

    routes.register(app, socketio, cfg, db, camera=camera, camera_lock=app.config["WASTE_CAMERA_LOCK"])
    return app, socketio
