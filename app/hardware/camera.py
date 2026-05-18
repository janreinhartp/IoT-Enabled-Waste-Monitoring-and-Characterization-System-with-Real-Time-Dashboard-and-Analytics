"""USB camera capture via OpenCV.

Provides :class:`Camera` interface and :class:`OpenCVCamera` implementation
using ``cv2.VideoCapture``. A mock implementation lives in :mod:`app.hardware.mock`.
"""

from __future__ import annotations

from typing import Optional, Protocol

import numpy as np

from app.config import AppConfig
from app.utils import get_logger

log = get_logger(__name__)


class Camera(Protocol):
    def capture(self) -> Optional[np.ndarray]:
        """Capture a single BGR frame. Returns None if capture failed."""

    def close(self) -> None:
        """Release the camera device."""


class OpenCVCamera:
    """Capture frames from a USB camera using OpenCV."""

    def __init__(self, index: int = 0, width: int = 640, height: int = 480):
        import cv2  # noqa: WPS433 - local import to keep test envs light

        self._cv2 = cv2
        self._cap = cv2.VideoCapture(index)
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open USB camera at index {index}")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    def capture(self) -> Optional[np.ndarray]:
        # Discard one stale buffered frame, then grab a fresh one
        self._cap.grab()
        ok, frame = self._cap.read()
        if not ok:
            log.warning("Camera capture failed")
            return None
        return frame

    def close(self) -> None:
        try:
            self._cap.release()
        except Exception:  # noqa: BLE001
            pass


def build_camera(cfg: AppConfig) -> Camera:
    if cfg.hardware.use_mock:
        from .mock import MockCamera

        log.info("Using MockCamera")
        return MockCamera(width=cfg.hardware.camera.width, height=cfg.hardware.camera.height)
    c = cfg.hardware.camera
    log.info("Opening USB camera index=%d %dx%d", c.index, c.width, c.height)
    return OpenCVCamera(index=c.index, width=c.width, height=c.height)


def save_jpeg(frame: np.ndarray, path: str, quality: int = 85) -> None:
    """Save a BGR frame as JPEG."""
    import cv2  # noqa: WPS433

    cv2.imwrite(path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
