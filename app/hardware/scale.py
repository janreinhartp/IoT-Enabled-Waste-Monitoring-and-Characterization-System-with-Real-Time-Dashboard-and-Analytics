"""Scale interface (NAU7802 + 4 load cells via Wheatstone bridge).

Provides:
  * :class:`Scale` - abstract interface
  * :class:`NAU7802Scale` - real driver (Adafruit CircuitPython lib)
  * :func:`build_scale` - factory selecting real or mock based on config
  * :class:`StableEventDetector` - turns a stream of weight samples into
    discrete "something was placed on the scale" events
"""

from __future__ import annotations

import statistics
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Protocol

from app.config import AppConfig
from app.utils import get_logger

log = get_logger(__name__)


class Scale(Protocol):
    """Abstract scale interface."""

    def read_grams(self) -> float:
        """Return current weight in grams (already tared & calibrated)."""

    def tare(self, samples: int = 16) -> None:
        """Capture a new tare offset by averaging ``samples`` raw readings."""

    def close(self) -> None:
        """Release hardware resources."""


# ----------------------------------------------------------------------------
# Real NAU7802 driver
# ----------------------------------------------------------------------------


class NAU7802Scale:
    """Driver for the NAU7802 24-bit ADC with a 4-load-cell Wheatstone bridge.

    Uses ``adafruit_nau7802`` which talks over I2C. Each load cell is wired
    so that the four together form a single Wheatstone bridge feeding
    Channel 1 of the NAU7802.
    """

    def __init__(
        self,
        *,
        i2c_address: int = 0x2A,
        gain: int = 128,
        calibration_factor: float = 1.0,
        tare_offset: int = 0,
    ):
        # Lazy imports so non-Pi machines can import this module.
        import board  # type: ignore[import-not-found]
        import busio  # type: ignore[import-not-found]
        import adafruit_nau7802  # type: ignore[import-not-found]

        self._i2c = busio.I2C(board.SCL, board.SDA)
        self._nau = adafruit_nau7802.NAU7802(self._i2c, address=i2c_address)
        self._nau.gain = gain
        self._nau.enable(True)
        self._calibration_factor = calibration_factor
        self._tare_offset = tare_offset

    def _read_raw(self) -> int:
        # Block until a sample is ready (the lib raises if not ready)
        while not self._nau.available():
            time.sleep(0.005)
        return int(self._nau.read())

    def read_raw_average(self, samples: int = 8) -> float:
        return sum(self._read_raw() for _ in range(samples)) / samples

    def read_grams(self) -> float:
        raw = self._read_raw()
        return (raw - self._tare_offset) / self._calibration_factor

    def tare(self, samples: int = 16) -> None:
        self._tare_offset = int(self.read_raw_average(samples))
        log.info("Tare offset set to %d", self._tare_offset)

    @property
    def tare_offset(self) -> int:
        return self._tare_offset

    @property
    def calibration_factor(self) -> float:
        return self._calibration_factor

    def set_calibration_factor(self, factor: float) -> None:
        self._calibration_factor = factor

    def close(self) -> None:  # pragma: no cover - hardware path
        try:
            self._nau.enable(False)
        except Exception:  # noqa: BLE001
            pass


# ----------------------------------------------------------------------------
# Factory
# ----------------------------------------------------------------------------


def build_scale(cfg: AppConfig) -> Scale:
    """Create a real or mock scale based on configuration."""
    if cfg.hardware.use_mock:
        from .mock import MockScale

        log.info("Using MockScale (set hardware.use_mock=false to use real hardware)")
        return MockScale()
    sc = cfg.hardware.scale
    log.info("Initializing NAU7802 at 0x%02X", sc.i2c_address)
    return NAU7802Scale(
        i2c_address=sc.i2c_address,
        gain=sc.gain,
        calibration_factor=sc.calibration_factor,
        tare_offset=sc.tare_offset,
    )


# ----------------------------------------------------------------------------
# Stable placement event detection
# ----------------------------------------------------------------------------


@dataclass
class StableEvent:
    """A detected stable placement event."""

    weight_grams: float


class StableEventDetector:
    """Detect "something was placed on the scale" events from a sample stream.

    State machine:
      * IDLE: waiting for weight to rise above ``min_weight_g``.
      * STABILIZING: weight is above threshold; collecting samples until the
        last ``stability_window`` samples have stddev <= ``stability_g``.
        When stable, emit an event and move to COOLDOWN.
      * COOLDOWN: ignore further samples until weight drops below
        ``reset_threshold_g`` (to prevent re-recording the same item).
    """

    IDLE = "idle"
    STABILIZING = "stabilizing"
    COOLDOWN = "cooldown"

    def __init__(
        self,
        *,
        min_weight_g: float,
        stability_window: int,
        stability_g: float,
        reset_threshold_g: float,
    ):
        if stability_window < 2:
            raise ValueError("stability_window must be >= 2")
        self.min_weight_g = min_weight_g
        self.stability_window = stability_window
        self.stability_g = stability_g
        self.reset_threshold_g = reset_threshold_g
        self._window: Deque[float] = deque(maxlen=stability_window)
        self._state = self.IDLE

    @property
    def state(self) -> str:
        return self._state

    def reset(self) -> None:
        self._window.clear()
        self._state = self.IDLE

    def push(self, weight_g: float) -> Optional[StableEvent]:
        """Feed a new weight sample. Returns a StableEvent if one was just detected."""
        if self._state == self.COOLDOWN:
            if weight_g <= self.reset_threshold_g:
                self._window.clear()
                self._state = self.IDLE
            return None

        if self._state == self.IDLE:
            if weight_g >= self.min_weight_g:
                self._window.clear()
                self._window.append(weight_g)
                self._state = self.STABILIZING
            return None

        # STABILIZING
        self._window.append(weight_g)
        if weight_g < self.min_weight_g:
            # Item lifted before stabilizing — reset
            self._window.clear()
            self._state = self.IDLE
            return None

        if len(self._window) < self.stability_window:
            return None

        # SQLite's pstdev would be fine; use stdlib stdev with n>=2
        stddev = statistics.pstdev(self._window)
        if stddev <= self.stability_g:
            mean = sum(self._window) / len(self._window)
            self._state = self.COOLDOWN
            return StableEvent(weight_grams=mean)
        return None
