"""Mock hardware for development on non-Pi machines."""

from __future__ import annotations

import random
import threading
import time
from typing import List, Optional

import numpy as np

from app.utils import get_logger

log = get_logger(__name__)


class MockScale:
    """Simulates a scale that goes through "place item / remove item" cycles.

    External code may call :meth:`set_weight` to deterministically drive
    the simulation (useful for tests). When no override is set it follows
    a simple random walk between empty and a random item weight.
    """

    def __init__(self):
        self._weight = 0.0
        self._target = 0.0
        self._lock = threading.Lock()
        self._next_change = time.monotonic() + 3.0

    def set_weight(self, grams: float) -> None:
        with self._lock:
            self._weight = grams
            self._target = grams

    def _maybe_advance(self) -> None:
        now = time.monotonic()
        if now < self._next_change:
            return
        with self._lock:
            if self._target == 0.0:
                # Place a random item: 20-1500 g
                self._target = random.uniform(20.0, 1500.0)
            else:
                self._target = 0.0
            self._next_change = now + random.uniform(4.0, 9.0)

    def read_grams(self) -> float:
        self._maybe_advance()
        with self._lock:
            # Drift toward target so we get a "settle" phase.
            delta = self._target - self._weight
            self._weight += delta * 0.4
            # Tiny noise so stability detection has something to work on
            noise = random.uniform(-0.15, 0.15)
            return max(0.0, self._weight + noise)

    def read_raw_average(self, samples: int = 8) -> float:
        """Mock raw voltage – always returns 0.0 (calibration needs real hardware)."""
        return 0.0

    def tare(self, samples: int = 16) -> None:
        with self._lock:
            self._weight = 0.0
            self._target = 0.0

    def close(self) -> None:
        return


class MockCamera:
    """Returns synthetic frames. Cycles through a few solid colors so the
    captured-image path can be exercised end-to-end."""

    _COLORS: List[tuple] = [
        (40, 90, 200),   # red-ish (BGR)
        (60, 180, 75),   # green-ish
        (200, 130, 0),   # blue-ish
        (180, 180, 180), # grey
    ]

    def __init__(self, width: int = 640, height: int = 480):
        self._width = width
        self._height = height
        self._idx = 0

    def capture(self) -> Optional[np.ndarray]:
        color = self._COLORS[self._idx % len(self._COLORS)]
        self._idx += 1
        frame = np.zeros((self._height, self._width, 3), dtype=np.uint8)
        frame[:] = color
        return frame

    def close(self) -> None:
        return
