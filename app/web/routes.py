"""HTTP + Socket.IO routes for the web dashboard."""

from __future__ import annotations

import csv
import io
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    render_template,
    request,
    send_file,
)
from flask_socketio import SocketIO

from app.config import AppConfig
from app.core.db import Database


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def register(
    app: Flask,
    socketio: SocketIO,
    cfg: AppConfig,
    db: Database,
    *,
    camera=None,
    camera_lock: Optional[threading.Lock] = None,
) -> None:
    """Register all HTTP routes and Socket.IO handlers."""

    # Module-level state so broadcast_bin_status can update it and on_connect
    # can send the current value to freshly connected clients.
    _bin_state: dict = {"full": False}

    # ---- Pages ----

    @app.get("/")
    def dashboard():
        categories = db.list_categories()
        recent = [e.to_dict() for e in db.list_events(limit=10)]
        return render_template(
            "dashboard.html", categories=categories, recent=recent
        )

    @app.get("/analytics")
    def analytics():
        categories = db.list_categories()
        return render_template("analytics.html", categories=categories)

    # ---- JSON API ----

    @app.get("/api/events")
    def api_events():
        limit = min(int(request.args.get("limit", 100)), 1000)
        offset = max(int(request.args.get("offset", 0)), 0)
        category = request.args.get("category")
        since = _parse_dt(request.args.get("since"))
        until = _parse_dt(request.args.get("until"))
        events = db.list_events(
            limit=limit, offset=offset, category=category, since=since, until=until
        )
        return jsonify([e.to_dict() for e in events])

    @app.get("/api/summary")
    def api_summary():
        window = request.args.get("window", "all")  # all | today | week
        since = None
        if window == "today":
            since = datetime.utcnow().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        elif window == "week":
            since = datetime.utcnow() - timedelta(days=7)
        return jsonify(db.summary(since=since))

    @app.get("/api/daily")
    def api_daily():
        days = max(1, min(int(request.args.get("days", 14)), 90))
        return jsonify(db.daily_totals(days=days))

    @app.get("/api/categories")
    def api_categories():
        return jsonify(db.list_categories())

    @app.get("/api/bin_status")
    def api_bin_status():
        return jsonify({
            "bin_full": _bin_state["full"],
            "capacity_kg": cfg.events.capacity_kg,
        })

    @app.get("/api/events.csv")
    def api_events_csv():
        events = db.list_events(limit=10000)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            ["id", "timestamp", "weight_grams", "label", "category", "confidence", "image"]
        )
        for e in events:
            writer.writerow(
                [
                    e.id,
                    e.timestamp.isoformat(),
                    f"{e.weight_grams:.2f}",
                    e.detected_label,
                    e.waste_category,
                    f"{e.confidence:.3f}",
                    e.image_path or "",
                ]
            )
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=waste_events.csv"},
        )

    # ---- Image serving ----

    @app.get("/images/<int:event_id>")
    def event_image(event_id: int):
        # Look up the event directly
        with db.session() as s:
            from app.core.db import WasteEvent  # local import

            ev = s.get(WasteEvent, event_id)
            if ev is None or not ev.image_path:
                abort(404)
            path = ev.image_path
        if not os.path.isfile(path):
            abort(404)
        return send_file(path, mimetype="image/jpeg")

    # ---- Live camera MJPEG stream ----

    @app.get("/video_feed")
    def video_feed():
        if camera is None:
            abort(404)

        def _generate():
            import cv2  # noqa: WPS433
            _lock = camera_lock or threading.Lock()
            while True:
                with _lock:
                    frame = camera.capture()
                if frame is None:
                    time.sleep(0.1)
                    continue
                ok, buf = cv2.imencode(
                    ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70]
                )
                if not ok:
                    time.sleep(0.1)
                    continue
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + buf.tobytes()
                    + b"\r\n"
                )
                time.sleep(1 / 15)  # ~15 fps

        return Response(
            _generate(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )

    # ---- Socket.IO ----

    @socketio.on("connect")
    def on_connect():  # noqa: D401 - Socket.IO handler
        # Send a snapshot of recent state to a freshly connected client.
        recent = [e.to_dict() for e in db.list_events(limit=10)]
        socketio.emit("snapshot", {
            "recent": recent,
            "bin_full": _bin_state["full"],
            "capacity_kg": cfg.events.capacity_kg,
        })

    # Expose _bin_state so broadcast_bin_status (below) can mutate it.
    app.config["_bin_state"] = _bin_state


def broadcast_event(socketio: SocketIO, event_dict: dict) -> None:
    """Push a new event to all connected clients."""
    socketio.emit("new_event", event_dict)


def broadcast_weight(socketio: SocketIO, grams: float) -> None:
    """Push a live weight update."""
    socketio.emit("weight", {"grams": grams})


def broadcast_bin_status(app: Flask, socketio: SocketIO, is_full: bool) -> None:
    """Push a bin-full / bin-emptied status change to all connected clients."""
    bin_state = app.config.get("_bin_state")
    if bin_state is not None:
        bin_state["full"] = is_full
    socketio.emit("bin_status", {"bin_full": is_full})
