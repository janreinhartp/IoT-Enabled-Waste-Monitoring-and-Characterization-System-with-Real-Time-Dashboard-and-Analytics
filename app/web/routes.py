"""HTTP + Socket.IO routes for the web dashboard."""

from __future__ import annotations

import csv
import hmac
import io
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional

from flask import (
    Flask,
    Response,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
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


def _check_credentials(username: str, password: str, cfg: AppConfig) -> bool:
    """Compare provided credentials against config using constant-time comparison."""
    user_ok = hmac.compare_digest(username.encode(), cfg.web.admin_username.encode())
    pass_ok = hmac.compare_digest(password.encode(), cfg.web.admin_password.encode())
    return user_ok and pass_ok


def _require_admin(f):
    """Decorator: redirect to /login when the admin session is not active."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated


def _require_admin_api(f):
    """Decorator for JSON API endpoints: return 401 instead of redirecting."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return jsonify({"error": "Unauthorized. Please log in as admin."}), 401
        return f(*args, **kwargs)
    return decorated


def register(
    app: Flask,
    socketio: SocketIO,
    cfg: AppConfig,
    db: Database,
    *,
    camera=None,
    camera_lock: Optional[threading.Lock] = None,
    scale=None,
) -> None:
    """Register all HTTP routes and Socket.IO handlers."""

    # Module-level state so broadcast_bin_status can update it and on_connect
    # can send the current value to freshly connected clients.
    _bin_state: dict = {"full": False}

    # Weight display helpers — computed once from config.
    # Decimal places come from the scale hardware setting so there is only
    # ONE place to configure them (hardware.scale.decimal_places).
    _UNIT_DIVISORS = {"g": 1.0, "kg": 1000.0}
    _w_symbol = cfg.web.display_unit
    _w_divisor = _UNIT_DIVISORS.get(cfg.web.display_unit, 1.0)
    _w_decimals = cfg.hardware.scale.decimal_places  # single source of truth

    @app.context_processor
    def _weight_display_ctx():
        """Inject weight-formatting helpers into every Jinja template."""
        def format_weight(grams: float) -> str:
            return f"{grams / _w_divisor:.{_w_decimals}f} {_w_symbol}"
        return {
            "format_weight": format_weight,
            "w_symbol": _w_symbol,
            "w_divisor": _w_divisor,
            "w_decimals": _w_decimals,
        }

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

    @app.get("/settings")
    @_require_admin
    def settings():
        from app.core.db import WasteEvent  # local import
        with db.session() as s:
            event_count = s.query(WasteEvent).count()
        return render_template(
            "settings.html",
            event_count=event_count,
        )

    # ---- Auth ----

    @app.get("/login")
    def login():
        if session.get("admin_logged_in"):
            return redirect(url_for("settings"))
        next_url = request.args.get("next", url_for("settings"))
        return render_template("login.html", next=next_url, error=None)

    @app.post("/login")
    def login_post():
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        next_url = request.form.get("next", url_for("settings"))
        if _check_credentials(username, password, cfg):
            session["admin_logged_in"] = True
            session.permanent = False
            # Guard against open-redirect: only allow relative paths
            if not next_url.startswith("/") or next_url.startswith("//"):
                next_url = url_for("settings")
            return redirect(next_url)
        return render_template("login.html", next=next_url, error="Invalid username or password.")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("dashboard"))

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

    @app.get("/api/hourly")
    def api_hourly():
        hours = max(1, min(int(request.args.get("hours", 24)), 168))
        return jsonify(db.hourly_totals(hours=hours))

    @app.get("/api/categories")
    def api_categories():
        return jsonify(db.list_categories())

    @app.get("/api/bin_status")
    def api_bin_status():
        return jsonify({
            "bin_full": _bin_state["full"],
            "capacity_kg": cfg.events.capacity_kg,
        })

    @app.post("/api/reset_db")
    @_require_admin_api
    def api_reset_db():
        deleted = db.reset_events()
        return jsonify({"deleted": deleted, "status": "ok"})

    @app.post("/api/record")
    def api_record():
        """Commit a pending detection (if any) or trigger a fresh capture + record."""
        pipeline = app.config.get("WASTE_PIPELINE")
        if pipeline is None:
            return jsonify({"error": "Pipeline not running (start without --no-pipeline)."}), 400
        pipeline.record_now()
        return jsonify({"status": "recording", "weight_g": round(pipeline.latest_weight, 1)})

    @app.post("/api/reset_tare")
    def api_reset_tare():
        """Cancel the current scale tare, restoring the gross-weight baseline.

        Call this when the physical bin is emptied and a fresh tare baseline
        is needed without pressing Analyze again.
        """
        pipeline = app.config.get("WASTE_PIPELINE")
        if pipeline is None:
            return jsonify({"error": "Pipeline not running."}), 400
        ok = pipeline.reset_tare()
        if not ok:
            return jsonify({"error": "Tare reset failed (check scale connection)."}), 500
        return jsonify({"status": "tare_reset"})

    @app.post("/api/analyze")
    def api_analyze():
        """Step 1 of the two-step flow: capture, run AI, save image, store as pending.

        The pending detection is held in memory until ``/api/commit`` is called.
        Returns the detection result so the dashboard can show what was seen.
        """
        pipeline = app.config.get("WASTE_PIPELINE")
        if pipeline is None:
            return jsonify({"error": "Pipeline not running."}), 400
        pending = pipeline.analyze_and_hold()
        if pending is None:
            return jsonify({"status": "no_detection", "message": "Nothing detected in frame."}), 200
        return jsonify({"status": "pending", **pending.to_dict()})

    @app.post("/api/commit")
    def api_commit():
        """Step 2 of the two-step flow: attach current weight to the pending detection and save.

        Returns 409 when there is no pending detection (Analyze must be called first).
        """
        pipeline = app.config.get("WASTE_PIPELINE")
        if pipeline is None:
            return jsonify({"error": "Pipeline not running."}), 400
        ok = pipeline.commit_pending()
        if not ok:
            return jsonify({"error": "No pending detection. Press Analyze first."}), 409
        return jsonify({"status": "recorded", "weight_g": round(pipeline.latest_weight, 1)})

    @app.get("/api/pending_detection")
    def api_pending_detection():
        """Return the current pending detection state (for dashboard polling)."""
        pipeline = app.config.get("WASTE_PIPELINE")
        if pipeline is None:
            return jsonify({"pending": False})
        pending = pipeline.pending_detection
        if pending is None:
            return jsonify({"pending": False})
        return jsonify({"pending": True, **pending.to_dict()})

    @app.post("/api/detect/preview")
    def api_detect_preview():
        """Capture a frame and run the detector without saving.

        Returns what the AI currently sees — useful for debugging why
        Record Now is not recording anything.  Includes labels that are
        detected but not (yet) mapped to a waste category so you know
        exactly what the model sees.
        """
        pipeline = app.config.get("WASTE_PIPELINE")
        if pipeline is None:
            return jsonify({"error": "Pipeline not running."}), 400
        detections = pipeline.detect_preview()
        return jsonify({
            "detections": [
                {
                    "label": d["label"],
                    "category": d.get("category"),   # None when unmapped
                    "confidence": round(d["confidence"], 3),
                }
                for d in detections
            ],
            "weight_g": round(pipeline.latest_weight, 1),
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

    @app.get("/images/pending")
    def pending_image():
        """Serve the captured image for the current pending detection."""
        pipeline = app.config.get("WASTE_PIPELINE")
        if pipeline is None:
            abort(404)
        pending = pipeline.pending_detection
        if pending is None or not pending.image_path:
            abort(404)
        abs_path = os.path.abspath(pending.image_path)
        if not os.path.isfile(abs_path):
            abort(404)
        return send_file(abs_path, mimetype="image/jpeg")

    @app.get("/images/<int:event_id>")
    def event_image(event_id: int):
        # Look up the event directly
        with db.session() as s:
            from app.core.db import WasteEvent  # local import

            ev = s.get(WasteEvent, event_id)
            if ev is None or not ev.image_path:
                abort(404)
            path = ev.image_path
        # Resolve to absolute so send_file works regardless of cwd.
        abs_path = os.path.abspath(path)
        if not os.path.isfile(abs_path):
            abort(404)
        return send_file(abs_path, mimetype="image/jpeg")

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


def broadcast_scale_status(socketio: SocketIO, status: dict) -> None:
    """Push scale detector state to all connected clients."""
    socketio.emit("scale_status", status)


def broadcast_ai_preview(socketio: SocketIO, detections: list) -> None:
    """Push a live AI preview update to all connected clients.

    ``detections`` is a list of dicts with keys ``label``, ``confidence``,
    and ``category`` (``None`` when the label is not mapped to a category).
    """
    socketio.emit("ai_preview", {"detections": detections})
