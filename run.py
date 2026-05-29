"""Entry point: starts the pipeline (background thread) and the web server."""

from __future__ import annotations

# eventlet.monkey_patch() MUST be called before any other imports so that
# stdlib socket/threading/time are replaced with eventlet-aware versions.
# Without this the MJPEG streaming generator blocks the greenlet scheduler
# and the camera feed never reaches the browser.
import eventlet

eventlet.monkey_patch()

import argparse
import signal
import sys

from app.ai.detector import build_detector
from app.config import load_config
from app.core.db import Database
from app.core.pipeline import Pipeline
from app.hardware.camera import build_camera
from app.hardware.scale import build_scale
from app.utils import setup_logging, get_logger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="IoT Waste Monitoring System")
    parser.add_argument(
        "-c", "--config", help="Path to config.yaml (defaults to ./config.yaml)"
    )
    parser.add_argument(
        "--no-pipeline",
        action="store_true",
        help="Run only the web server (no hardware loop). Useful for inspecting stored data.",
    )
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    setup_logging(cfg.logging.level)
    log = get_logger("run")

    log.info("Initializing database at %s", cfg.database.url)
    db = Database(cfg.database.url)
    db.create_all()

    # Build Flask + SocketIO
    from app.web.routes import broadcast_event, broadcast_weight, broadcast_bin_status, broadcast_scale_status, broadcast_ai_preview
    from app.web.server import create_app
    import threading

    pipeline = None
    camera = None
    camera_lock = threading.Lock()
    if not args.no_pipeline:
        log.info("Initializing hardware (use_mock=%s)", cfg.hardware.use_mock)
        scale = build_scale(cfg)
        camera = build_camera(cfg)
        detector = build_detector(cfg)

    app, socketio = create_app(cfg, db, camera=camera, camera_lock=camera_lock, scale=scale if not args.no_pipeline else None)

    if not args.no_pipeline:
        pipeline = Pipeline(
            cfg,
            scale=scale,
            camera=camera,
            detector=detector,
            db=db,
            camera_lock=camera_lock,
            on_event=lambda rec: broadcast_event(socketio, rec.to_dict()),
            on_weight=lambda g: broadcast_weight(socketio, g),
            on_bin_status=lambda full: broadcast_bin_status(app, socketio, full),
            on_scale_status=lambda s: broadcast_scale_status(socketio, s),
            on_ai_preview=lambda dets: broadcast_ai_preview(socketio, dets),
        )
        pipeline.start()
        app.config["WASTE_PIPELINE"] = pipeline

    def _shutdown(*_args):
        log.info("Shutting down…")
        if pipeline:
            pipeline.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info("Web server listening on http://%s:%d", cfg.web.host, cfg.web.port)
    socketio.run(
        app,
        host=cfg.web.host,
        port=cfg.web.port,
        debug=cfg.web.debug,
        allow_unsafe_werkzeug=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
