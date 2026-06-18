"""Physical push-button driver for the "Analyze & Record" button.

A momentary push-button wired between a GPIO pin and GND triggers
:meth:`Pipeline.record_now` — the same action as the web dashboard's
"Record Now" button, but operable without a screen or network connection.

Wiring
------
Connect one leg of the button to the chosen GPIO pin and the other leg
to any GND pin.  The internal pull-up resistor is enabled in software,
so no external resistor is required::

    GPIO pin ──┬── [ Button ] ── GND
               └── (internal pull-up, normally HIGH → LOW on press)

The default GPIO pin is **BCM 17** (physical pin 11) — change it in
``config.yaml`` under ``hardware.button.gpio_pin``.

Provides
--------
* :class:`ButtonWatcher`  – real GPIO driver (RPi.GPIO)
* :class:`MockButton`     – development stub; simulates a press every N seconds
* :func:`build_button`    – factory; returns ``None`` when button is disabled
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from app.config import AppConfig
from app.utils import get_logger

log = get_logger(__name__)

PressCallback = Callable[[], None]


# ---------------------------------------------------------------------------
# Real GPIO driver
# ---------------------------------------------------------------------------


class ButtonWatcher:
    """Monitors a GPIO pin and fires a callback on each button press.

    Uses RPi.GPIO edge detection with software debouncing.

    Args:
        gpio_pin:        BCM-numbered GPIO pin (default 17 / physical pin 11).
        debounce_ms:     Minimum milliseconds between accepted presses (default 300).
        on_press:        Callable invoked (in a daemon thread) on each press.
    """

    def __init__(
        self,
        *,
        gpio_pin: int = 17,
        debounce_ms: int = 300,
        on_press: PressCallback,
    ):
        import RPi.GPIO as GPIO  # type: ignore[import-not-found]

        self._gpio_pin = gpio_pin
        self._on_press = on_press
        self._GPIO = GPIO

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        # Full reset of the pin to clear any state left by a previous crashed run.
        # cleanup() unexports the sysfs entry and removes edge detection in the kernel.
        try:
            GPIO.remove_event_detect(gpio_pin)
        except Exception:  # noqa: BLE001
            pass
        try:
            GPIO.cleanup(gpio_pin)
        except Exception:  # noqa: BLE001
            pass
        GPIO.setup(gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        # FALLING = button pressed (pin goes HIGH→LOW)
        GPIO.add_event_detect(
            gpio_pin,
            GPIO.FALLING,
            callback=self._isr,
            bouncetime=debounce_ms,
        )
        log.info(
            "ButtonWatcher ready on BCM GPIO%d (debounce=%d ms)", gpio_pin, debounce_ms
        )

    def _isr(self, channel: int) -> None:  # noqa: ARG002
        """Interrupt service routine — fires in RPi.GPIO's internal thread."""
        log.info("Button pressed (GPIO%d)", self._gpio_pin)
        threading.Thread(target=self._on_press, daemon=True, name=f"btn-gpio{self._gpio_pin}").start()

    def close(self) -> None:
        """Remove event detection and clean up GPIO."""
        try:
            self._GPIO.remove_event_detect(self._gpio_pin)
            self._GPIO.cleanup(self._gpio_pin)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Mock driver
# ---------------------------------------------------------------------------


class MockButton:
    """Development stub that simulates a button press every ``interval_s`` seconds.

    Useful for testing the record flow on a laptop without real hardware.
    Set ``interval_s=0`` to disable automatic simulation (button never fires).
    """

    def __init__(self, *, on_press: PressCallback, interval_s: float = 15.0):
        self._on_press = on_press
        self._interval_s = interval_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        if interval_s > 0:
            self._thread = threading.Thread(
                target=self._loop, daemon=True, name="mock-btn"
            )
            self._thread.start()
            log.info(
                "MockButton started (simulated press every %.0f s)", interval_s
            )
        else:
            log.info("MockButton created with interval_s=0 (no auto-press)")

    def _loop(self) -> None:
        while not self._stop.wait(self._interval_s):
            log.info("MockButton: simulating button press")
            threading.Thread(
                target=self._on_press, daemon=True, name="mock-btn-record"
            ).start()

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_button(
    cfg: AppConfig,
    on_press: PressCallback,
    *,
    config_override=None,
) -> Optional[ButtonWatcher | MockButton]:
    """Return a button watcher or ``None`` when the button is disabled.

    Args:
        cfg:             Global app config (used for ``use_mock`` flag).
        on_press:        Callable fired on each button press.
        config_override: A :class:`~app.config.ButtonConfig` instance to use
                         instead of ``cfg.hardware.button``.  Pass
                         ``cfg.hardware.button_analyze`` or
                         ``cfg.hardware.button_record`` to select the
                         appropriate button configuration.

    * ``ButtonConfig.enabled: false``  → returns ``None``
    * ``hardware.use_mock: true``      → returns :class:`MockButton`
    * otherwise                        → returns :class:`ButtonWatcher`
    """
    btn_cfg = config_override if config_override is not None else cfg.hardware.button_analyze
    if not btn_cfg.enabled:
        log.info("Button disabled on GPIO%d (enabled=false)", btn_cfg.gpio_pin)
        return None

    if cfg.hardware.use_mock:
        log.info("Using MockButton for GPIO%d (hardware.use_mock=true)", btn_cfg.gpio_pin)
        return MockButton(on_press=on_press, interval_s=btn_cfg.mock_interval_s)

    return ButtonWatcher(
        gpio_pin=btn_cfg.gpio_pin,
        debounce_ms=btn_cfg.debounce_ms,
        on_press=on_press,
    )
