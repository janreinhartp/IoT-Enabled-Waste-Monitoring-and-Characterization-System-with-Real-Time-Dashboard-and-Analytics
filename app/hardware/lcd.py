"""I2C LCD display driver (HD44780 + PCF8574 backpack).

Displays the live weight reading and the latest AI detection on a
character LCD connected to the Raspberry Pi over I²C.

Supported layouts
-----------------
16×2 LCD (default, address 0x27)::

    Row 0:  " 1234.5g  STABLE"   ← weight + detector state
    Row 1:  "Sees: plastic    "   ← top AI detection label

20×4 LCD (address 0x27 or 0x3F)::

    Row 0:  "Weight:  1234.5 g   "
    Row 1:  "Status: Stable      "
    Row 2:  "Sees: plastic bottle"
    Row 3:  "Conf:  95.0%        "

Wiring (Feiyang-style PCF8574 I²C backpack)
-------------------------------------------
    LCD backpack  →  Raspberry Pi
    VCC           →  Pin 2  (5V)
    GND           →  Pin 6  (GND)
    SDA           →  Pin 3  (GPIO 2, SDA1)
    SCL           →  Pin 5  (GPIO 3, SCL1)

Enable I²C with ``sudo raspi-config`` → Interface Options → I2C → Yes.

Provides
--------
* :class:`LCD`       – abstract Protocol
* :class:`I2CLCD`    – real driver (RPLCD + smbus2)
* :class:`MockLCD`   – development stub (logs to stdout)
* :func:`build_lcd`  – factory; returns ``None`` when LCD is disabled
"""

from __future__ import annotations

import threading
from typing import Optional, Protocol

from app.config import AppConfig
from app.utils import get_logger

log = get_logger(__name__)

# Abbreviations for the detector state shown on constrained 16-col displays.
_STATE_ABBR = {
    "idle":         "IDLE  ",
    "stabilizing":  "STABLE",
    "cooldown":     "COOL  ",
}


class LCD(Protocol):
    """Abstract LCD interface."""

    def show_weight(self, grams: float, state: str) -> None:
        """Update the weight / detector-state rows."""

    def show_detection(self, label: str, confidence: float) -> None:
        """Update the AI-detection rows."""

    def show_message(self, row0: str, row1: str = "") -> None:
        """Write arbitrary text to the first two rows (for alerts etc.)."""

    def close(self) -> None:
        """Turn off backlight and release the I²C bus."""


# ---------------------------------------------------------------------------
# Real I²C driver
# ---------------------------------------------------------------------------


class I2CLCD:
    """HD44780 character LCD driven over I²C via a PCF8574 backpack.

    Uses the ``RPLCD`` library with ``smbus2`` as the I²C backend.

    Args:
        i2c_address:  PCF8574 I²C address (0x27 or 0x3F are most common).
        cols:         Number of character columns (16 or 20).
        rows:         Number of character rows (2 or 4).
        i2c_port:     I²C bus number (1 on all Raspberry Pi 2/3/4/5).
    """

    def __init__(
        self,
        *,
        i2c_address: int = 0x27,
        cols: int = 16,
        rows: int = 2,
        i2c_port: int = 1,
    ):
        # Lazy import — only available on Pi with RPLCD installed.
        from RPLCD.i2c import CharLCD  # type: ignore[import-not-found]

        self._cols = cols
        self._rows = rows
        self._lock = threading.Lock()

        self._lcd = CharLCD(
            i2c_expander="PCF8574",
            address=i2c_address,
            port=i2c_port,
            cols=cols,
            rows=rows,
            dotsize=8,
            charmap="A02",
            auto_linebreaks=False,
            backlight_enabled=True,
        )
        self._lcd.clear()
        log.info(
            "I2CLCD initialised: %dx%d at 0x%02X (I²C bus %d)",
            cols, rows, i2c_address, i2c_port,
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def show_weight(self, grams: float, state: str) -> None:
        """Update weight and detector-state rows."""
        if self._cols >= 20:
            self._write_row(0, f"Weight:{grams:9.1f} g")
            self._write_row(1, f"Status: {state.capitalize()}")
        else:
            abbr = _STATE_ABBR.get(state, state[:6].upper())
            g_str = f"{grams:.1f}g"
            self._write_row(0, f"{g_str:<10}{abbr:>6}")

    def show_detection(self, label: str, confidence: float) -> None:
        """Update the AI-detection rows."""
        if self._cols >= 20:
            self._write_row(2, f"Sees: {label}")
            self._write_row(3, f"Conf: {confidence * 100:5.1f}%")
        else:
            self._write_row(1, f"Sees: {label}")

    def show_message(self, row0: str, row1: str = "") -> None:
        """Write arbitrary text to the first two rows."""
        self._write_row(0, row0)
        if self._rows >= 2:
            self._write_row(1, row1)

    def close(self) -> None:
        """Turn off backlight and close the I²C connection."""
        try:
            with self._lock:
                self._lcd.clear()
                self._lcd.backlight_enabled = False
                self._lcd.close(clear=True)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_row(self, row: int, text: str) -> None:
        if row >= self._rows:
            return
        padded = text[: self._cols].ljust(self._cols)
        with self._lock:
            self._lcd.cursor_pos = (row, 0)
            self._lcd.write_string(padded)


# ---------------------------------------------------------------------------
# Mock driver
# ---------------------------------------------------------------------------


class MockLCD:
    """Development stub — logs display updates instead of driving hardware."""

    def show_weight(self, grams: float, state: str) -> None:
        log.debug("[LCD] Weight: %.1f g  State: %s", grams, state)

    def show_detection(self, label: str, confidence: float) -> None:
        log.debug("[LCD] Sees: %s  Conf: %.0f%%", label, confidence * 100)

    def show_message(self, row0: str, row1: str = "") -> None:
        log.debug("[LCD] %s | %s", row0, row1)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_lcd(cfg: AppConfig) -> Optional[I2CLCD | MockLCD]:
    """Return an LCD instance or ``None`` if the LCD is disabled.

    * ``hardware.lcd.enabled: false``  → returns ``None`` (LCD skipped entirely)
    * ``hardware.use_mock: true``      → returns :class:`MockLCD`
    * otherwise                        → returns :class:`I2CLCD`
    """
    lcd_cfg = cfg.hardware.lcd
    if not lcd_cfg.enabled:
        log.info("LCD disabled (hardware.lcd.enabled=false)")
        return None

    if cfg.hardware.use_mock:
        log.info("Using MockLCD (hardware.use_mock=true)")
        return MockLCD()

    log.info(
        "Initializing I2CLCD at 0x%02X, %d×%d",
        lcd_cfg.i2c_address, lcd_cfg.cols, lcd_cfg.rows,
    )
    return I2CLCD(
        i2c_address=lcd_cfg.i2c_address,
        cols=lcd_cfg.cols,
        rows=lcd_cfg.rows,
        i2c_port=lcd_cfg.i2c_port,
    )
