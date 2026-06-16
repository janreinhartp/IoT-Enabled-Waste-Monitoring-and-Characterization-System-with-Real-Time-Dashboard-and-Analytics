"""Domain data classes shared by the pipeline and web layer."""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Detection:
    """Result of running the AI detector on a captured frame."""

    label: str
    category: str
    confidence: float


@dataclass
class PendingDetection:
    """An analyzed frame that has been captured and AI-processed but not yet
    weighed.  Created by :meth:`Pipeline.analyze_and_hold` (Analyze button)
    and consumed by :meth:`Pipeline.commit_pending` (Record button).
    """

    image_path: str
    detections: List[Detection]

    def top(self) -> Optional[Detection]:
        """Return the highest-confidence detection, or None if empty."""
        return max(self.detections, key=lambda d: d.confidence) if self.detections else None

    def to_dict(self) -> Dict[str, Any]:
        top = self.top()
        return {
            "image_path": self.image_path,
            "label": top.label if top else None,
            "category": top.category if top else None,
            "confidence": round(top.confidence, 3) if top else None,
            "all_detections": [
                {"label": d.label, "category": d.category, "confidence": round(d.confidence, 3)}
                for d in self.detections
            ],
        }


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
