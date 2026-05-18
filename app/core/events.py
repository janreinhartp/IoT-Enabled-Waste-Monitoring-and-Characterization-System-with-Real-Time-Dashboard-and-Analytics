"""Domain data classes shared by the pipeline and web layer."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class Detection:
    """Result of running the AI detector on a captured frame."""

    label: str
    category: str
    confidence: float


@dataclass
class WasteEventRecord:
    """A persisted weighing + detection event, as exposed to the web layer."""

    id: int
    timestamp: datetime
    weight_grams: float
    detected_label: str
    waste_category: str
    confidence: float
    image_path: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d
