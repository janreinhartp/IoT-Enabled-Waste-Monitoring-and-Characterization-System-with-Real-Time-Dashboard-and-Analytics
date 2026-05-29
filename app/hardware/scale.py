"""Scale interface (ADS1115 voltage reading on channel 1).

Provides:
  * :class:`Scale` - abstract interface
  * :class:`ADS1115Scale` - real driver (Adafruit CircuitPython ADS1x15 lib)
  * :func:`build_scale` - factory selecting real or mock based on config
  * :class:`StableEventDetector` - turns a stream of weight samples into
    discrete "something was placed on the scale" events
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Protocol

from app.config import AppConfig
from app.utils import get_logger

log = get_logger(__name__)

# Valid PGA gain values accepted by the adafruit_ads1x15 library.
_VALID_GAINS = [2 / 3, 1, 2, 4, 8, 16]


def _nearest_gain(value: float) -> float:
    """Return the ADS1115 gain value closest to *value*."""
    return min(_VALID_GAINS, key=lambda g: abs(g - value))


class Scale(Protocol):
    """Abstract scale interface."""

    def read_grams(self) -> float:
        """Return current weight in grams (already tared & calibrated)."""

    def tare(self, samples: int = 16) -> None:
        """Capture a new tare offset by averaging ``samples`` raw readings."""

    def close(self) -> None:
        """Release hardware resources."""


# ----------------------------------------------------------------------------
# Real ADS1115 driver (Channel 1 / AIN1)
# ----------------------------------------------------------------------------


class ADS1115Scale:
    """Driver for the ADS1115 16-bit ADC reading voltage on channel 1 (AIN1).

    Uses ``adafruit_ads1x15`` which talks over I2C.  The analogue sensor
    output (e.g. a load-cell amplifier board) is wired to AIN1 of the
    ADS1115.  Voltage is converted to grams using a linear calibration:

        grams = (voltage_V - tare_offset_V) / calibration_factor_V_per_g
    """

    def __init__(
        self,
        *,
        i2c_address: int = 0x48,
        gain: float = 2 / 3,
        calibration_factor: float = 1.0,
        tare_offset: float = 0.0,
    ):
        # Lazy imports so non-Pi machines can import this module.
        import board  # type: ignore[import-not-found]
        import busio  # type: ignore[import-not-found]
        import adafruit_ads1x15.ads1115 as ADS  # type: ignore[import-not-found]
        from adafruit_ads1x15.ads1x15 import Pin  # type: ignore[import-not-found]
        from adafruit_ads1x15.analog_in import AnalogIn  # type: ignore[import-not-found]

        self._i2c = busio.I2C(board.SCL, board.SDA)
        self._ads = ADS.ADS1115(self._i2c, address=i2c_address)
        self._ads.gain = _nearest_gain(gain)
        self._chan = AnalogIn(self._ads, Pin.A0)  # Channel 0 (AIN0)
        self._calibration_factor = calibration_factor
        self._tare_offset = tare_offset

    def _read_voltage(self) -> float:
        return self._chan.voltage

    def read_raw_average(self, samples: int = 8) -> float:
        return sum(self._read_voltage() for _ in range(samples)) / samples

    def read_grams(self, samples: int = 4) -> float:
        """Return current weight in grams, averaged over ``samples`` readings."""
        voltage = self.read_raw_average(samples)
        return (voltage - self._tare_offset) / self._calibration_factor

    def tare(self, samples: int = 16) -> None:
        self._tare_offset = self.read_raw_average(samples)
        log.info("Tare offset set to %.6f V", self._tare_offset)

    @property
    def tare_offset(self) -> float:
        return self._tare_offset

    @property
    def calibration_factor(self) -> float:
        return self._calibration_factor

    def set_calibration_factor(self, factor: float) -> None:
        self._calibration_factor = factor

    def close(self) -> None:  # pragma: no cover - hardware path
        try:
            self._i2c.deinit()
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
    log.info("Initializing ADS1115 at 0x%02X, channel 0", sc.i2c_address)
    return ADS1115Scale(
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
