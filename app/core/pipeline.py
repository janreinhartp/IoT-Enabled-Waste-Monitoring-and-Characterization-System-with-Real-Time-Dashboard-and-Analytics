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
from app.core.events import Detection, PendingDetection, WasteEventRecord
from app.hardware.camera import Camera, save_jpeg
from app.hardware.scale import Scale, StableEventDetector
from app.utils import get_logger

log = get_logger(__name__)

# Optional LCD — imported lazily to avoid hard dependency on RPLCD.
try:
    from app.hardware.lcd import LCD
except Exception:  # noqa: BLE001
    LCD = object  # type: ignore[assignment,misc]


EventCallback = Callable[[WasteEventRecord], None]
WeightCallback = Callable[[float], None]
BinStatusCallback = Callable[[bool], None]
ScaleStatusCallback = Callable[[dict], None]
AIPreviewCallback = Callable[[list], None]


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
        on_ai_preview: Optional[AIPreviewCallback] = None,
        lcd=None,
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
        self._on_ai_preview = on_ai_preview
        self._lcd = lcd
        self._lcd_weight_interval = 0.5   # update LCD weight at most every 0.5 s
        self._lcd_last_weight_ts = 0.0
        self._detector_state = StableEventDetector(
            min_weight_g=cfg.events.min_weight_g,
            stability_window=cfg.events.stability_window,
            stability_g=cfg.events.stability_g,
            reset_threshold_g=cfg.events.reset_threshold_g,
        )
        self._thread: Optional[threading.Thread] = None
        self._preview_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._latest_weight = 0.0
        self._bin_full = False
        # Pending detection: set by analyze_and_hold(), consumed by commit_pending()
        self._pending: Optional[PendingDetection] = None
        self._pending_lock = threading.Lock()
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
        # Start continuous AI preview thread if a callback is registered and
        # the interval is configured.
        interval = self._cfg.ai.ai_preview_interval_s
        if self._on_ai_preview and interval and interval > 0:
            self._preview_thread = threading.Thread(
                target=self._ai_preview_loop, name="waste-ai-preview", daemon=True
            )
            self._preview_thread.start()
            log.info("AI preview thread started (interval=%.1fs)", interval)
        log.info("Pipeline started")

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        if self._preview_thread:
            self._preview_thread.join(timeout=timeout)
        log.info("Pipeline stopped")

    @property
    def latest_weight(self) -> float:
        return self._latest_weight

    @property
    def bin_full(self) -> bool:
        return self._bin_full

    @property
    def pending_detection(self) -> Optional[PendingDetection]:
        """The most recently analyzed (but not yet recorded) detection, or None."""
        with self._pending_lock:
            return self._pending

    # ------------------------------------------------------------------
    # Two-step Analyze → Record flow
    # ------------------------------------------------------------------

    def analyze_and_hold(self) -> Optional[PendingDetection]:
        """Step 1 — Capture frame, run AI, save image, store as pending.

        Call this when the **Analyze** button is pressed while the item is
        still in front of the camera.  The image is saved to disk immediately
        so it is preserved even if the item is moved before :meth:`commit_pending`
        is called.

        Returns the :class:`PendingDetection` on success, or ``None`` when
        the camera is unavailable or nothing is detected.
        """
        log.info("analyze_and_hold: capturing frame")
        frame = self._safe_capture()
        if frame is None:
            log.warning("analyze_and_hold: camera unavailable")
            return None

        detections = self._safe_detect_all(frame)
        if not detections:
            log.info("analyze_and_hold: no detections in frame")
            return None

        image_path = self._save_image(frame)
        pending = PendingDetection(image_path=image_path, detections=detections)
        with self._pending_lock:
            self._pending = pending
        top = pending.top()
        log.info(
            "analyze_and_hold: pending set — %s (%.0f%%) image=%s",
            top.label if top else "?",
            (top.confidence * 100) if top else 0,
            image_path,
        )
        return pending

    def commit_pending(self, weight_g: Optional[float] = None) -> bool:
        """Step 2 — Attach the current scale weight to the pending detection and save.

        Call this when the **Record** button is pressed after the item has been
        moved onto the scale and the weight has settled.

        Args:
            weight_g: Override weight in grams. Uses the latest live reading
                      when not provided.

        Returns:
            ``True`` if a pending detection was committed, ``False`` if there
            was nothing pending (you should call :meth:`analyze_and_hold` first).
        """
        with self._pending_lock:
            pending = self._pending
            if pending is None:
                log.warning("commit_pending: no pending detection — press Analyze first")
                return False
            self._pending = None  # consume immediately

        g = weight_g if weight_g is not None else self._latest_weight
        log.info("commit_pending: recording pending detection at %.2f g", g)
        self._save_event_from_pending(pending, g)
        return True

    def clear_pending(self) -> None:
        """Discard any pending detection without recording it."""
        with self._pending_lock:
            self._pending = None
        log.info("clear_pending: pending detection cleared")

    def record_now(self) -> None:
        """Manually trigger a record at the current live weight.

        If a pending detection exists (Analyze was already pressed) it is
        committed with the current weight.  Otherwise a fresh capture + detect
        cycle runs (legacy behaviour — useful from the web dashboard).
        """
        with self._pending_lock:
            has_pending = self._pending is not None
        if has_pending:
            threading.Thread(
                target=self.commit_pending,
                name="waste-commit-pending",
                daemon=True,
            ).start()
        else:
            weight = self._latest_weight
            threading.Thread(
                target=self._handle_event,
                args=(weight,),
                name="waste-manual-record",
                daemon=True,
            ).start()

    def detect_preview(self) -> List[dict]:
        """Capture a frame and run the detector without saving anything.

        Uses :meth:`~app.ai.detector.TFLiteDetector.preview_all` when
        available so the result includes raw model predictions above a low
        threshold (0.10) *and* labels that have no waste-category mapping.
        This lets the dashboard show exactly what the AI sees — helping
        debug why ``record_now`` might not be recording anything.

        Returns a list of dicts with keys ``label``, ``confidence``, and
        ``category`` (``None`` when the label is not mapped to a category).
        """
        frame = self._safe_capture()
        if frame is None:
            return []
        if hasattr(self._detector, "preview_all"):
            try:
                return self._detector.preview_all(frame)  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                log.exception("preview_all failed; falling back to detect_all")
        return [
            {"label": d.label, "confidence": d.confidence, "category": d.category}
            for d in self._safe_detect_all(frame)
        ]

    # ------------------------------------------------------------------
    # Continuous AI preview loop
    # ------------------------------------------------------------------

    def _ai_preview_loop(self) -> None:
        """Background thread: runs preview_all() periodically and calls on_ai_preview.

        Runs at ``cfg.ai.ai_preview_interval_s`` second intervals. Skipped when
        the main pipeline thread is busy with an event (camera lock held). Uses
        a low-priority sleep so it does not compete with the scale loop.
        """
        interval = self._cfg.ai.ai_preview_interval_s
        while not self._stop.is_set():
            self._stop.wait(interval)
            if self._stop.is_set():
                break
            try:
                detections = self.detect_preview()
                if self._on_ai_preview:
                    self._on_ai_preview(detections)
                # Update LCD detection line with the top-confidence result
                if self._lcd:
                    if detections:
                        top = max(detections, key=lambda d: d["confidence"])
                        try:
                            self._lcd.show_detection(top["label"], top["confidence"])
                        except Exception:  # noqa: BLE001
                            log.exception("LCD detection update failed")
                    else:
                        try:
                            self._lcd.show_detection("Nothing", 0.0)
                        except Exception:  # noqa: BLE001
                            pass
            except Exception:  # noqa: BLE001
                log.exception("AI preview loop error")

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

            # Update LCD weight display at ~2 Hz (avoids flooding I²C bus)
            if self._lcd and (t0 - self._lcd_last_weight_ts) >= self._lcd_weight_interval:
                self._lcd_last_weight_ts = t0
                try:
                    self._lcd.show_weight(grams, self._detector_state.state)
                except Exception:  # noqa: BLE001
                    log.exception("LCD weight update failed")

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
        """Auto-stable or legacy record-now path: capture, detect, save."""
        log.info("Stable placement detected: %.2f g", weight_g)
        frame = self._safe_capture()
        detections = self._safe_detect_all(frame)

        image_path: Optional[str] = None
        if frame is not None:
            image_path = self._save_image(frame)

        if not detections:
            log.info("No recognizable items detected in frame; event skipped.")
            return

        pending = PendingDetection(image_path=image_path or "", detections=detections)
        self._save_event_from_pending(pending, weight_g)

    def _save_event_from_pending(self, pending: PendingDetection, weight_g: float) -> None:
        """Persist DB rows and fire callbacks for a completed detection + weight."""
        if not pending.detections:
            log.info("No detections in pending record; skipping.")
            return

        image_path = pending.image_path or None

        # Split weight equally among all detected items.
        weight_per_item = weight_g / len(pending.detections)
        for detection in pending.detections:
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
