"""End-to-end pipeline: scale → camera → AI → DB → Socket.IO broadcast."""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Callable, Optional

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


class Pipeline:
    """Runs the sample loop in a background thread.

    On each weighing event it captures a frame, runs the detector, saves
    the image to disk, persists a row to the DB, and calls user-supplied
    callbacks for live-weight updates and new events (used by the web
    layer to push Socket.IO messages).
    """

    def __init__(
        self,
        cfg: AppConfig,
        *,
        scale: Scale,
        camera: Camera,
        detector: Detector,
        db: Database,
        on_event: Optional[EventCallback] = None,
        on_weight: Optional[WeightCallback] = None,
    ):
        self._cfg = cfg
        self._scale = scale
        self._camera = camera
        self._detector = detector
        self._db = db
        self._on_event = on_event
        self._on_weight = on_weight
        self._detector_state = StableEventDetector(
            min_weight_g=cfg.events.min_weight_g,
            stability_window=cfg.events.stability_window,
            stability_g=cfg.events.stability_g,
            reset_threshold_g=cfg.events.reset_threshold_g,
        )
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._latest_weight = 0.0
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

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        rate = max(1, int(self._cfg.hardware.scale.sample_rate_hz))
        interval = 1.0 / rate
        last_broadcast = 0.0
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

            event = self._detector_state.push(grams)
            if event is not None:
                self._handle_event(event.weight_grams)

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
        detection = self._safe_detect(frame)

        image_path: Optional[str] = None
        if frame is not None:
            image_path = self._save_image(frame)

        if detection is None:
            detection = Detection(label="unknown", category="unknown", confidence=0.0)

        record = self._db.insert_event(
            weight_grams=weight_g,
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
            return self._camera.capture()
        except Exception:  # noqa: BLE001
            log.exception("Camera capture failed")
            return None

    def _safe_detect(self, frame: Optional[np.ndarray]) -> Optional[Detection]:
        if frame is None:
            return None
        try:
            return self._detector.detect(frame)
        except Exception:  # noqa: BLE001
            log.exception("Detector failed")
            return None

    def _save_image(self, frame: np.ndarray) -> Optional[str]:
        try:
            name = f"{int(time.time())}-{uuid.uuid4().hex[:8]}.jpg"
            full = os.path.join(self._cfg.storage.images_dir, name)
            save_jpeg(frame, full, quality=self._cfg.hardware.camera.jpeg_quality)
            return full
        except Exception:  # noqa: BLE001
            log.exception("Image save failed")
            return None
