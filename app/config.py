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
    i2c_address: int = 0x2A
    calibration_factor: float = 1000.0
    tare_offset: int = 0
    gain: int = 128
    sample_rate_hz: int = 10


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


@dataclass
class EventsConfig:
    min_weight_g: float = 5.0
    stability_window: int = 8
    stability_g: float = 1.0
    reset_threshold_g: float = 2.0


@dataclass
class AIConfig:
    backend: str = "mock"
    model_path: str = "app/ai/models/efficientdet_lite0.tflite"
    labels_path: str = "app/ai/models/coco_labels.txt"
    min_confidence: float = 0.4
    input_size: int = 320


@dataclass
class DatabaseConfig:
    url: str = "sqlite:///data/waste.db"


@dataclass
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 5000
    debug: bool = False
    secret_key: str = "change-me-in-production"


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
