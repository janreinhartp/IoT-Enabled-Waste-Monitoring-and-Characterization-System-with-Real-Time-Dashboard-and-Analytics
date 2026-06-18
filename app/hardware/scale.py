"""Scale interface — RS485 Modbus RTU driver.

Register map (from module datasheet):
  0–1   Real-time net weight     (Double word, signed 32-bit, little-endian word order)
  2–3   Stable value hold        (Double word, signed 32-bit, little-endian word order)
  6     Status flags             (Word — Bit0: steady/stable flag)
  17    Peeling operation        (Single word — write 1=tare, 2=cancel tare, 3=clear peak)
  18    Calibration operation    (Single word — write 1=zero cal, 2=weight point cal)

Communication: Modbus RTU, 9600 baud (default), 8 data bits, 1 stop bit, no parity.

Raw integer → grams conversion:
    grams = (raw_int / 10 ** decimal_places) * unit_to_grams

Example: module calibrated in kg, 2 decimal places → decimal_places=2, unit_to_grams=1000.0
         module calibrated in grams, 0 decimal places → decimal_places=0, unit_to_grams=1.0

Provides:
  * :class:`Scale`              – abstract Protocol
  * :class:`ModbusRTUScale`     – real RS485 Modbus RTU driver (minimalmodbus)
  * :func:`build_scale`         – factory selecting real or mock based on config
  * :class:`StableEventDetector`– turns a weight sample stream into placement events
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Protocol

from app.config import AppConfig
from app.utils import get_logger

log = get_logger(__name__)

# Modbus register addresses (from datasheet)
_REG_NET_WEIGHT = 0       # Double word (regs 0–1): real-time net weight
_REG_STABLE_WEIGHT = 2    # Double word (regs 2–3): stable value hold
_REG_STATUS = 6           # Word: Bit0 = steady/stable flag
_REG_PEEL = 17            # Single word: peeling / tare operations
_REG_CALIBRATION = 18     # Single word: calibration operations

_PEEL_TARE = 1            # Write to _REG_PEEL to tare
_PEEL_CANCEL_TARE = 2     # Write to _REG_PEEL to cancel tare
_PEEL_CLEAR_PEAK = 3      # Write to _REG_PEEL to clear peak

_CAL_ZERO = 1             # Write to _REG_CALIBRATION for zero calibration
_CAL_WEIGHT_POINT = 2     # Write to _REG_CALIBRATION for weight point calibration

_STABLE_BIT = 0x0001      # Bit0 of status register


def _combine_registers(low_reg: int, high_reg: int) -> int:
    """Combine two 16-bit Modbus registers into a signed 32-bit integer.

    The module uses little-endian word order: the lower address register
    holds the low 16 bits and the higher address register holds the high 16 bits.
    """
    raw = (high_reg << 16) | low_reg
    if raw > 0x7FFFFFFF:  # two's complement for negative weights
        raw -= 0x100000000
    return raw


class Scale(Protocol):
    """Abstract scale interface."""

    def read_grams(self) -> float:
        """Return current net weight in grams (tare handled by the module)."""

    def tare(self, samples: int = 16) -> None:
        """Send a tare (peel) command to the scale module."""

    def close(self) -> None:
        """Release hardware resources."""


# ----------------------------------------------------------------------------
# Real RS485 Modbus RTU driver
# ----------------------------------------------------------------------------


class ModbusRTUScale:
    """RS485 Modbus RTU driver for the weight indicator module.

    Communicates over a serial RS485 adapter (e.g. USB-to-RS485 dongle or a
    Raspberry Pi UART with a MAX485 transceiver).

    The module performs tare, calibration and stability detection internally;
    this driver simply reads the net weight registers and issues tare commands.

    Args:
        port:           Serial port path, e.g. ``/dev/ttyUSB0`` or ``COM3``.
        slave_address:  Modbus slave address of the module (default 1).
        baud_rate:      Serial baud rate — 9600 / 19200 / 38400 (default 9600).
        decimal_places: Number of decimal places encoded in the register value.
                        The raw integer is divided by ``10**decimal_places``.
        unit_to_grams:  Multiplier to convert from the module's calibrated unit
                        to grams (1.0 if grams, 1000.0 if kg).
        timeout:        Modbus reply timeout in seconds (default 1.0).
    """

    def __init__(
        self,
        *,
        port: str,
        slave_address: int = 1,
        baud_rate: int = 9600,
        decimal_places: int = 0,
        unit_to_grams: float = 1.0,
        timeout: float = 1.0,
    ):
        # Lazy import so non-Pi machines can import this module without
        # minimalmodbus installed (tests use MockScale instead).
        import minimalmodbus  # type: ignore[import-not-found]
        import serial  # type: ignore[import-not-found]

        self._decimal_places = decimal_places
        self._unit_to_grams = unit_to_grams

        instrument = minimalmodbus.Instrument(port, slave_address)
        instrument.serial.baudrate = baud_rate
        instrument.serial.bytesize = 8
        instrument.serial.parity = serial.PARITY_NONE
        instrument.serial.stopbits = 1
        instrument.serial.timeout = timeout
        instrument.mode = minimalmodbus.MODE_RTU
        instrument.clear_buffers_before_each_transaction = True
        self._instrument = instrument

        log.info(
            "ModbusRTUScale initialised on %s, slave=%d, baud=%d",
            port, slave_address, baud_rate,
        )

    def _raw_to_grams(self, raw: int) -> float:
        return (raw / (10 ** self._decimal_places)) * self._unit_to_grams

    def _read_double_word(self, start_register: int) -> int:
        """Read two consecutive 16-bit registers and combine into signed 32-bit int."""
        regs = self._instrument.read_registers(start_register, 2, functioncode=3)
        return _combine_registers(regs[0], regs[1])

    def read_grams(self) -> float:
        """Return the real-time net weight in grams."""
        raw = self._read_double_word(_REG_NET_WEIGHT)
        return self._raw_to_grams(raw)

    def read_stable_grams(self) -> float:
        """Return the last stable net weight in grams.

        The module only updates this value when the weight reading is stable;
        it holds the previous stable value while the weight fluctuates.
        """
        raw = self._read_double_word(_REG_STABLE_WEIGHT)
        return self._raw_to_grams(raw)

    def is_stable(self) -> bool:
        """Return True when the module reports a stable/settled reading."""
        status = self._instrument.read_register(_REG_STATUS, functioncode=3)
        return bool(status & _STABLE_BIT)

    def tare(self, samples: int = 16) -> None:  # noqa: ARG002 – samples unused
        """Send a tare (peel) command to the module.

        The module zeros its net weight register and updates the internal tare
        value.  The ``samples`` parameter is accepted for interface compatibility
        but is not used (tare is performed by the module, not by averaging).
        """
        self._instrument.write_register(_REG_PEEL, _PEEL_TARE, functioncode=6)
        log.info("Tare command sent to scale module")

    def cancel_tare(self) -> None:
        """Cancel the most recent tare, restoring the previous tare value."""
        self._instrument.write_register(_REG_PEEL, _PEEL_CANCEL_TARE, functioncode=6)
        log.info("Cancel-tare command sent to scale module")

    def zero_calibrate(self) -> None:
        """Trigger an internal zero-point calibration on the module."""
        self._instrument.write_register(_REG_CALIBRATION, _CAL_ZERO, functioncode=6)
        log.info("Zero calibration command sent to scale module")

    def weight_point_calibrate(self, known_weight_raw: int) -> None:
        """Trigger a weight-point calibration with a known reference weight.

        Args:
            known_weight_raw: The reference weight expressed as a raw integer
                              (i.e. already scaled by 10**decimal_places and
                              divided by unit_to_grams). For example, if the
                              module is in kg with 2 decimal places, 5 kg is
                              represented as 500.
        """
        # Write the known weight value to registers 8–9 (double word)
        low_word = known_weight_raw & 0xFFFF
        high_word = (known_weight_raw >> 16) & 0xFFFF
        self._instrument.write_registers(_REG_CALIBRATION - 10, [low_word, high_word])  # regs 8–9
        self._instrument.write_register(_REG_CALIBRATION, _CAL_WEIGHT_POINT, functioncode=6)
        log.info("Weight-point calibration triggered (raw value=%d)", known_weight_raw)

    def close(self) -> None:
        """Release the serial port."""
        try:
            self._instrument.serial.close()
        except Exception:  # noqa: BLE001
            pass
        log.info("ModbusRTUScale serial port closed")


# ----------------------------------------------------------------------------
# Modbus TCP driver (Waveshare RS485 TO ETH (B) or similar gateway)
# ----------------------------------------------------------------------------


class ModbusTCPScale:
    """Modbus TCP driver for the weight indicator module.

    Use this instead of :class:`ModbusRTUScale` when the RS485 bus is bridged
    to Ethernet via a gateway such as the **Waveshare RS485 TO ETH (B)**.
    The gateway must be configured in **Modbus TCP ↔ RTU** mode (port 502).

    The Pi no longer needs a UART or TTL↔RS485 adapter — it talks to the
    gateway over the same Ethernet/Wi-Fi network as the dashboard.

    Args:
        host:           IP address of the RS485-to-Ethernet gateway
                        (e.g. ``"192.168.1.200"``).
        tcp_port:       TCP port — 502 in Modbus TCP↔RTU mode (recommended).
        slave_address:  Modbus slave address of the weight indicator (default 1).
        decimal_places: Decimal places encoded in the register value.
        unit_to_grams:  Multiplier from module unit to grams.
        timeout:        Modbus reply timeout in seconds (default 1.0).
    """

    def __init__(
        self,
        *,
        host: str,
        tcp_port: int = 502,
        slave_address: int = 1,
        decimal_places: int = 0,
        unit_to_grams: float = 1.0,
        timeout: float = 1.0,
    ):
        # Lazy import — pymodbus is optional; serial-only deployments don't need it.
        import pymodbus  # type: ignore[import-not-found]  # noqa: PLC0415
        from pymodbus.client import ModbusTcpClient  # type: ignore[import-not-found]

        self._decimal_places = decimal_places
        self._unit_to_grams = unit_to_grams

        # pymodbus 2.x uses 'unit=', pymodbus 3.x renamed it to 'slave='.
        # Detect once at init so every Modbus call uses the right kwarg.
        _major = int(pymodbus.__version__.split(".")[0])
        self._slave_kw: dict = {"slave": slave_address} if _major >= 3 else {"unit": slave_address}
        log.debug("pymodbus version %s detected; using kwarg %s",
                  pymodbus.__version__, next(iter(self._slave_kw)))

        self._client = ModbusTcpClient(host=host, port=tcp_port, timeout=timeout)
        if not self._client.connect():
            raise ConnectionError(
                f"Cannot connect to Modbus TCP gateway at {host}:{tcp_port}. "
                "Check that the Waveshare module is powered, the Ethernet cable is "
                "plugged in, and the gateway IP/port match config.yaml."
            )

        log.info(
            "ModbusTCPScale connected to %s:%d (slave=%d, pymodbus=%s)",
            host, tcp_port, slave_address, pymodbus.__version__,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _raw_to_grams(self, raw: int) -> float:
        return (raw / (10 ** self._decimal_places)) * self._unit_to_grams

    def _read_double_word(self, start_register: int) -> int:
        """Read two consecutive 16-bit registers and combine into a signed 32-bit int."""
        result = self._client.read_holding_registers(
            address=start_register, count=2, **self._slave_kw
        )
        if result.isError():
            raise IOError(
                f"Modbus TCP read error at register {start_register}: {result}"
            )
        return _combine_registers(result.registers[0], result.registers[1])

    # ------------------------------------------------------------------
    # Scale Protocol implementation
    # ------------------------------------------------------------------

    def read_grams(self) -> float:
        """Return the real-time net weight in grams."""
        raw = self._read_double_word(_REG_NET_WEIGHT)
        return self._raw_to_grams(raw)

    def read_stable_grams(self) -> float:
        """Return the last stable net weight in grams."""
        raw = self._read_double_word(_REG_STABLE_WEIGHT)
        return self._raw_to_grams(raw)

    def is_stable(self) -> bool:
        """Return True when the module reports a stable/settled reading."""
        result = self._client.read_holding_registers(
            address=_REG_STATUS, count=1, **self._slave_kw
        )
        if result.isError():
            return False
        return bool(result.registers[0] & _STABLE_BIT)

    def tare(self, samples: int = 16) -> None:  # noqa: ARG002
        """Send a tare command to the module."""
        self._client.write_register(
            address=_REG_PEEL, value=_PEEL_TARE, **self._slave_kw
        )
        log.info("Tare command sent to scale module (TCP)")

    def cancel_tare(self) -> None:
        """Cancel the most recent tare."""
        self._client.write_register(
            address=_REG_PEEL, value=_PEEL_CANCEL_TARE, **self._slave_kw
        )
        log.info("Cancel-tare command sent to scale module (TCP)")

    def zero_calibrate(self) -> None:
        """Trigger zero-point calibration on the module."""
        self._client.write_register(
            address=_REG_CALIBRATION, value=_CAL_ZERO, **self._slave_kw
        )
        log.info("Zero calibration command sent to scale module (TCP)")

    def weight_point_calibrate(self, known_weight_raw: int) -> None:
        """Trigger weight-point calibration with a known reference weight."""
        low_word = known_weight_raw & 0xFFFF
        high_word = (known_weight_raw >> 16) & 0xFFFF
        self._client.write_registers(
            address=_REG_CALIBRATION - 10, values=[low_word, high_word], **self._slave_kw
        )
        self._client.write_register(
            address=_REG_CALIBRATION, value=_CAL_WEIGHT_POINT, **self._slave_kw
        )
        log.info(
            "Weight-point calibration triggered via TCP (raw value=%d)", known_weight_raw
        )

    def close(self) -> None:
        """Close the TCP connection."""
        self._client.close()
        log.info("ModbusTCPScale TCP connection closed")


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
    if sc.host:
        log.info(
            "Initializing ModbusTCPScale → %s:%d (slave=%d)",
            sc.host, sc.tcp_port, sc.slave_address,
        )
        return ModbusTCPScale(
            host=sc.host,
            tcp_port=sc.tcp_port,
            slave_address=sc.slave_address,
            decimal_places=sc.decimal_places,
            unit_to_grams=sc.unit_to_grams,
            timeout=sc.timeout,
        )
    log.info(
        "Initializing ModbusRTUScale on %s (slave=%d, baud=%d)",
        sc.port, sc.slave_address, sc.baud_rate,
    )
    return ModbusRTUScale(
        port=sc.port,
        slave_address=sc.slave_address,
        baud_rate=sc.baud_rate,
        decimal_places=sc.decimal_places,
        unit_to_grams=sc.unit_to_grams,
        timeout=sc.timeout,
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
