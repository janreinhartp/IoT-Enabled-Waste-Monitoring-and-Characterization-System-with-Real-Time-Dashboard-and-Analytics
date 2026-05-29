"""End-to-end pipeline: scale → camera → AI → DB → Socket.IO broadcast."""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Callable, List, Optional

import numpy as np

from app.ai.detector import Detector
from app.config import AppConfig
from app.core.db import Database
from app.core.events import Detection, WasteEventRecord
from app.hardware.camera import Camera, save_jpeg
from app.hardware.scale import Scale, StableEventDetector
from app.utils import get_logger

log = get_logger(__name__)


EventCallback = Callable[[WasteEventRecord], None]
WeightCallback = Callable[[float], None]
BinStatusCallback = Callable[[bool], None]
ScaleStatusCallback = Callable[[dict], None]


class Pipeline:
    """Runs the sample loop in a background thread.

    On each weighing event it captures a frame, runs the detector, saves
    the image to disk, persists one DB row per detected item, and calls
    user-supplied callbacks for live-weight updates, new events, and bin
    status changes (used by the web layer to push Socket.IO messages).

    Bin capacity: when the cumulative weight on the scale reaches
    ``events.capacity_kg`` kg the pipeline stops accepting new placements
    and emits a ``bin_full=True`` status. It resumes once the weight drops
    back below ``events.reset_threshold_g`` grams (bin emptied).
    """

    def __init__(
        self,
        cfg: AppConfig,
        *,
        scale: Scale,
        camera: Camera,
        detector: Detector,
        db: Database,
        camera_lock: Optional[threading.Lock] = None,
        on_event: Optional[EventCallback] = None,
        on_weight: Optional[WeightCallback] = None,
        on_bin_status: Optional[BinStatusCallback] = None,
        on_scale_status: Optional[ScaleStatusCallback] = None,
    ):
        self._cfg = cfg
        self._scale = scale
        self._camera = camera
        self._camera_lock = camera_lock
        self._detector = detector
        self._db = db
        self._on_event = on_event
        self._on_weight = on_weight
        self._on_bin_status = on_bin_status
        self._on_scale_status = on_scale_status
        self._detector_state = StableEventDetector(
            min_weight_g=cfg.events.min_weight_g,
            stability_window=cfg.events.stability_window,
            stability_g=cfg.events.stability_g,
            reset_threshold_g=cfg.events.reset_threshold_g,
        )
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._latest_weight = 0.0
        self._bin_full = False
        os.makedirs(cfg.storage.images_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Thread control
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="waste-pipeline", daemon=True
        )
        self._thread.start()
        log.info("Pipeline started")

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        log.info("Pipeline stopped")

    @property
    def latest_weight(self) -> float:
        return self._latest_weight

    @property
    def bin_full(self) -> bool:
        return self._bin_full

    def record_now(self) -> None:
        """Manually trigger a record using the current live weight.

        Runs in a background thread so the caller returns immediately.
        Useful for prototyping when the scale reading is noisy and the
        stable-event detector never fires.
        """
        weight = self._latest_weight
        threading.Thread(
            target=self._handle_event,
            args=(weight,),
            name="waste-manual-record",
            daemon=True,
        ).start()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        rate = max(1, int(self._cfg.hardware.scale.sample_rate_hz))
        interval = 1.0 / rate
        last_broadcast = 0.0
        capacity_g = self._cfg.events.capacity_kg * 1000.0

        while not self._stop.is_set():
            t0 = time.monotonic()
            try:
                grams = float(self._scale.read_grams())
            except Exception as exc:  # noqa: BLE001
                log.exception("Scale read failed: %s", exc)
                time.sleep(interval)
                continue
            self._latest_weight = grams

            # Throttle weight broadcasts to ~5 Hz
            if self._on_weight and (t0 - last_broadcast) > 0.2:
                try:
                    self._on_weight(grams)
                except Exception:  # noqa: BLE001
                    log.exception("on_weight callback failed")
                last_broadcast = t0

            # --- Bin capacity check ---
            was_full = self._bin_full
            self._bin_full = grams >= capacity_g
            if self._bin_full != was_full:
                if self._bin_full:
                    log.warning(
                        "BIN FULL: %.0f g >= %.0f g capacity. "
                        "No new events until bin is emptied.",
                        grams, capacity_g,
                    )
                else:
                    log.info("Bin emptied (%.0f g). Resuming event detection.", grams)
                if self._on_bin_status:
                    try:
                        self._on_bin_status(self._bin_full)
                    except Exception:  # noqa: BLE001
                        log.exception("on_bin_status callback failed")

            event = self._detector_state.push(grams)
            if event is not None and not self._bin_full:
                self._handle_event(event.weight_grams)

            # Broadcast scale detector status for the dashboard
            if self._on_scale_status:
                window_size = len(self._detector_state._window)
                try:
                    self._on_scale_status({
                        "state": self._detector_state.state,
                        "weight_g": round(grams, 1),
                        "window_samples": window_size,
                        "stability_window": self._cfg.events.stability_window,
                        "min_weight_g": self._cfg.events.min_weight_g,
                        "stability_g": self._cfg.events.stability_g,
                    })
                except Exception:  # noqa: BLE001
                    log.exception("on_scale_status callback failed")

            # Sleep for the remainder of the interval
            elapsed = time.monotonic() - t0
            remaining = interval - elapsed
            if remaining > 0:
                self._stop.wait(remaining)

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def _handle_event(self, weight_g: float) -> None:
        log.info("Stable placement detected: %.2f g", weight_g)
        frame = self._safe_capture()
        detections = self._safe_detect_all(frame)

        image_path: Optional[str] = None
        if frame is not None:
            image_path = self._save_image(frame)

        if not detections:
            log.info("No recognizable items detected in frame; event skipped.")
            return

        # Split weight equally among all detected items.
        weight_per_item = weight_g / len(detections)
        for detection in detections:
            record = self._db.insert_event(
                weight_grams=weight_per_item,
                detected_label=detection.label,
                category_slug=detection.category,
                confidence=detection.confidence,
                image_path=image_path,
            )
            log.info(
                "Recorded event #%d: %s (%s) %.0f g conf=%.2f",
                record.id,
                record.detected_label,
                record.waste_category,
                record.weight_grams,
                record.confidence,
            )
            if self._on_event:
                try:
                    self._on_event(record)
                except Exception:  # noqa: BLE001
                    log.exception("on_event callback failed")

    def _safe_capture(self) -> Optional[np.ndarray]:
        try:
            if self._camera_lock is not None:
                with self._camera_lock:
                    return self._camera.capture()
            return self._camera.capture()
        except Exception:  # noqa: BLE001
            log.exception("Camera capture failed")
            return None

    def _safe_detect_all(self, frame: Optional[np.ndarray]) -> List[Detection]:
        if frame is None:
            return []
        try:
            return self._detector.detect_all(frame)
        except Exception:  # noqa: BLE001
            log.exception("Detector failed")
            return []

    def _save_image(self, frame: np.ndarray) -> Optional[str]:
        try:
            name = f"{int(time.time())}-{uuid.uuid4().hex[:8]}.jpg"
            # Always store an absolute path so the web server can find the
            # file regardless of the working directory at serve time.
            full = os.path.abspath(os.path.join(self._cfg.storage.images_dir, name))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            save_jpeg(frame, full, quality=self._cfg.hardware.camera.jpeg_quality)
            log.debug("Image saved: %s", full)
            return full
        except Exception:  # noqa: BLE001
            log.exception("Image save failed")
            return None
