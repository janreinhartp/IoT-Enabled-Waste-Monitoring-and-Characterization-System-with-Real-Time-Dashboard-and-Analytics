"""Mapping from object-detection labels (e.g. COCO) to waste categories.

Supported categories: ``plastic``, ``paper``, ``metal``, ``glass``.
Labels that do not map to one of these four return ``None`` and are
ignored by the pipeline.
"""

from __future__ import annotations

from typing import Dict, List, Optional

# Detection-label (lowercase) -> waste category slug
LABEL_TO_CATEGORY: Dict[str, str] = {
    # Plastic
    "bottle": "plastic",
    "cup": "plastic",
    # Paper / cardboard
    "book": "paper",
    "newspaper": "paper",
    # Metal
    "can": "metal",
    "fork": "metal",
    "knife": "metal",
    "spoon": "metal",
    # Glass
    "wine glass": "glass",
    "vase": "glass",
    "jar": "glass",
}


def category_for(label: str) -> Optional[str]:
    """Return the waste category slug for a detection label.

    Returns ``None`` if the label does not map to a known category;
    the caller should discard such detections.
    """
    if not label:
        return None
    return LABEL_TO_CATEGORY.get(label.strip().lower())


def load_labels(path: str) -> List[str]:
    """Load a newline-separated labels file (e.g. coco_labels.txt).

    Each line may optionally be prefixed with an index, e.g. ``"0 person"``.
    """
    labels: List[str] = []
    with open(path, "r", encoding="utf-8") as fp:
        for raw in fp:
            line = raw.strip()
            if not line:
                continue
            parts = line.split(maxsplit=1)
            if len(parts) == 2 and parts[0].isdigit():
                labels.append(parts[1])
            else:
                labels.append(line)
    return labels
