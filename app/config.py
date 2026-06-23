"""Configuration loader.

Reads ``config.yaml`` (falling back to ``config.example.yaml``) into a
nested dataclass-like structure that the rest of the app can use.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

import yaml


@dataclass
class ScaleConfig:
    # RS485 serial port (e.g. /dev/ttyUSB0 on Linux, COM3 on Windows).
    # Ignored when host is set (TCP mode).
    port: str = "/dev/ttyUSB0"
    # Modbus slave address of the weight indicator module
    slave_address: int = 1
    # Baud rate — module supports 9600, 19200, 38400.
    # Ignored when host is set (TCP mode); the baud rate is instead configured
    # on the RS485-to-Ethernet gateway itself (e.g. Waveshare RS485 TO ETH (B)).
    baud_rate: int = 9600
    # Decimal places shown on the scale module's display / encoded in the register.
    # Set this to match exactly what the scale module displays (e.g. 3 for 15.000 kg).
    decimal_places: int = 2
    # Unit the scale module is calibrated in: "kg" or "g".
    # The driver uses this to convert the reading to grams for internal storage.
    scale_unit: str = "kg"
    # Modbus reply timeout in seconds
    timeout: float = 1.0
    # Samples per second the pipeline loop will try to read
    sample_rate_hz: int = 10
    # --- TCP / Ethernet mode (Waveshare RS485 TO ETH (B) or similar gateway) ---
    # Set host to the gateway IP to use Modbus TCP instead of serial RTU.
    # Leave empty ("") to use the serial RS485 driver above.
    host: str = ""
    # TCP port of the gateway. Use 502 when the gateway is in Modbus TCP↔RTU mode
    # (recommended). Use 4196 for raw transparent TCP mode.
    tcp_port: int = 502


@dataclass
class ButtonConfig:
    # Set to true to enable this button
    enabled: bool = False
    # BCM GPIO pin number (other leg of the button connects to GND)
    gpio_pin: int = 17
    # Software debounce time in milliseconds
    debounce_ms: int = 300
    # MockButton only: seconds between simulated presses (0 = disabled)
    mock_interval_s: float = 0.0


@dataclass
class LCDConfig:
    # Set to true to enable the I2C LCD display
    enabled: bool = False
    # PCF8574 I2C address (0x27 is the most common default; 0x3F on some modules)
    i2c_address: int = 0x27
    # Display dimensions — common options: 16x2 or 20x4
    cols: int = 16
    rows: int = 2
    # I2C bus number (1 on all Raspberry Pi 2/3/4/5)
    i2c_port: int = 1


@dataclass
class CameraConfig:
    index: int = 0
    width: int = 640
    height: int = 480
    jpeg_quality: int = 85


@dataclass
class HardwareConfig:
    use_mock: bool = True
    scale: ScaleConfig = field(default_factory=ScaleConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    lcd: LCDConfig = field(default_factory=LCDConfig)
    button_analyze: ButtonConfig = field(default_factory=lambda: ButtonConfig(gpio_pin=17))
    button_record: ButtonConfig = field(default_factory=lambda: ButtonConfig(gpio_pin=27))


@dataclass
class EventsConfig:
    min_weight_g: float = 5.0
    stability_window: int = 8
    stability_g: float = 1.0
    reset_threshold_g: float = 2.0
    capacity_kg: float = 100.0


@dataclass
class AIConfig:
    backend: str = "mock"
    model_path: str = "app/ai/models/efficientdet_lite0.tflite"
    labels_path: str = "app/ai/models/coco_labels.txt"
    min_confidence: float = 0.4
    input_size: int = 320
    # How often (seconds) to run a background AI preview and push via Socket.IO.
    # Set to 0 to disable continuous preview.
    ai_preview_interval_s: float = 2.0


@dataclass
class DatabaseConfig:
    url: str = "sqlite:///data/waste.db"


@dataclass
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 5000
    debug: bool = False
    secret_key: str = "change-me-in-production"
    # Admin credentials — protect the Settings page and DB reset
    admin_username: str = "admin"
    admin_password: str = "admin"
    # Weight display unit shown in the UI.  "g" keeps grams; "kg" divides by 1000.
    display_unit: str = "kg"
    # Number of decimal places for displayed weights
    display_decimals: int = 3


@dataclass
class StorageConfig:
    images_dir: str = "data/images"


@dataclass
class LoggingConfig:
    level: str = "INFO"


@dataclass
class AppConfig:
    hardware: HardwareConfig = field(default_factory=HardwareConfig)
    events: EventsConfig = field(default_factory=EventsConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    web: WebConfig = field(default_factory=WebConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def _merge(dc_cls, data: Dict[str, Any]):
    """Build a dataclass from a dict, recursively for nested dataclasses."""
    if data is None:
        return dc_cls()
    kwargs: Dict[str, Any] = {}
    for f in dc_cls.__dataclass_fields__.values():  # type: ignore[attr-defined]
        if f.name in data:
            value = data[f.name]
            ftype = f.type
            # Resolve string annotations to actual classes via globals
            if isinstance(ftype, str):
                ftype = globals().get(ftype, ftype)
            if isinstance(value, dict) and hasattr(ftype, "__dataclass_fields__"):
                kwargs[f.name] = _merge(ftype, value)
            else:
                kwargs[f.name] = value
    return dc_cls(**kwargs)





def load_config(path: str | os.PathLike | None = None) -> AppConfig:
    """Load configuration from YAML file.

    Search order:
      1. ``path`` argument (if provided)
      2. ``$WASTE_CONFIG`` environment variable
      3. ``config.yaml`` in the current working directory
      4. ``config.example.yaml`` in the current working directory
      5. Defaults
    """
    candidates = []
    if path:
        candidates.append(Path(path))
    env_path = os.environ.get("WASTE_CONFIG")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path("config.yaml"))
    candidates.append(Path("config.example.yaml"))

    for candidate in candidates:
        if candidate and candidate.is_file():
            with candidate.open("r", encoding="utf-8") as fp:
                data = yaml.safe_load(fp) or {}
            return _merge(AppConfig, data)

    return AppConfig()
