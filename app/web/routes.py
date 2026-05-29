"""HTTP + Socket.IO routes for the web dashboard."""

from __future__ import annotations

import csv
import io
import os
import sys
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
    scale=None,
) -> None:
    """Register all HTTP routes and Socket.IO handlers."""

    # Module-level state so broadcast_bin_status can update it and on_connect
    # can send the current value to freshly connected clients.
    _bin_state: dict = {"full": False}
    # Temporary tare voltage captured during step 1 of calibration.
    _calib_state: dict = {"tare_voltage": None}

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
    def settings():
        from app.core.db import WasteEvent  # local import
        with db.session() as s:
            event_count = s.query(WasteEvent).count()
        return render_template(
            "settings.html",
            event_count=event_count,
            use_mock=cfg.hardware.use_mock,
            tare_offset=cfg.hardware.scale.tare_offset,
            calibration_factor=cfg.hardware.scale.calibration_factor,
        )

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

    @app.post("/api/reset_db")
    def api_reset_db():
        deleted = db.reset_events()
        return jsonify({"deleted": deleted, "status": "ok"})

    @app.post("/api/record")
    def api_record():
        """Manually trigger a record at the current live weight."""
        pipeline = app.config.get("WASTE_PIPELINE")
        if pipeline is None:
            return jsonify({"error": "Pipeline not running (start without --no-pipeline)."}), 400
        pipeline.record_now()
        return jsonify({"status": "recording", "weight_g": round(pipeline.latest_weight, 1)})

    # ---- Scale calibration ----

    @app.get("/api/calibrate/status")
    def api_calibrate_status():
        return jsonify({
            "use_mock": cfg.hardware.use_mock,
            "tare_offset": cfg.hardware.scale.tare_offset,
            "calibration_factor": cfg.hardware.scale.calibration_factor,
            "tare_captured": _calib_state["tare_voltage"] is not None,
        })

    @app.post("/api/calibrate/tare")
    def api_calibrate_tare():
        if cfg.hardware.use_mock:
            return jsonify({"error": "Calibration requires real hardware (hardware.use_mock is true)."}), 400
        if scale is None:
            return jsonify({"error": "Scale not available (running with --no-pipeline)."}), 400
        try:
            tare_voltage = scale.read_raw_average(32)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": f"Scale read failed: {exc}"}), 500
        _calib_state["tare_voltage"] = tare_voltage
        return jsonify({"tare_voltage": tare_voltage, "status": "tare_captured"})

    @app.post("/api/calibrate/finish")
    def api_calibrate_finish():
        if cfg.hardware.use_mock:
            return jsonify({"error": "Calibration requires real hardware (hardware.use_mock is true)."}), 400
        if scale is None:
            return jsonify({"error": "Scale not available (running with --no-pipeline)."}), 400
        if _calib_state["tare_voltage"] is None:
            return jsonify({"error": "Run tare first."}), 400

        data = request.get_json(silent=True) or {}
        try:
            known_weight = float(data["known_weight"])
        except (KeyError, TypeError, ValueError):
            return jsonify({"error": "known_weight (grams) is required."}), 400
        if known_weight <= 0:
            return jsonify({"error": "known_weight must be positive."}), 400

        try:
            loaded_voltage = scale.read_raw_average(32)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": f"Scale read failed: {exc}"}), 500

        tare_voltage = _calib_state["tare_voltage"]
        delta = loaded_voltage - tare_voltage
        if abs(delta) < 1e-6:
            return jsonify({"error": "No change detected from tare. Check wiring."}), 400

        factor = delta / known_weight
        # Persist to config.yaml and update live config object.
        from app.config import save_scale_calibration
        config_path = os.environ.get("WASTE_CONFIG", "config.yaml")
        save_scale_calibration(tare_voltage, factor, config_path)
        cfg.hardware.scale.tare_offset = tare_voltage
        cfg.hardware.scale.calibration_factor = factor
        # Update the live scale object so it starts using new values immediately.
        if hasattr(scale, "_tare_offset"):
            scale._tare_offset = tare_voltage
        if hasattr(scale, "_calibration_factor"):
            scale._calibration_factor = factor
        _calib_state["tare_voltage"] = None

        # Schedule restart so the saved config is re-loaded cleanly.
        def _delayed_restart():
            time.sleep(2.0)
            os.execv(sys.executable, [sys.executable] + sys.argv)

        threading.Thread(target=_delayed_restart, daemon=True).start()

        return jsonify({
            "tare_offset": tare_voltage,
            "calibration_factor": factor,
            "verification_grams": delta / factor,
            "status": "saved_restarting",
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
