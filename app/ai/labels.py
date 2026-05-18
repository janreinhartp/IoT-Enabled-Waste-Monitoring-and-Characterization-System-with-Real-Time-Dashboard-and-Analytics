"""Mapping from object-detection labels (e.g. COCO) to waste categories.

The category slugs here must match the seeded categories in
:mod:`app.core.db` (``plastic``, ``paper``, ``metal``, ``glass``,
``organic``, ``residual``, ``unknown``).
"""

from __future__ import annotations

from typing import Dict, List

# Detection-label (lowercase) -> waste category slug
LABEL_TO_CATEGORY: Dict[str, str] = {
    # Plastic
    "bottle": "plastic",
    "cup": "plastic",
    "wine glass": "glass",
    "fork": "metal",
    "knife": "metal",
    "spoon": "metal",
    # Paper / cardboard
    "book": "paper",
    "newspaper": "paper",
    # Metal
    "can": "metal",
    # Glass
    "vase": "glass",
    # Organic / food
    "banana": "organic",
    "apple": "organic",
    "sandwich": "organic",
    "orange": "organic",
    "broccoli": "organic",
    "carrot": "organic",
    "hot dog": "organic",
    "pizza": "organic",
    "donut": "organic",
    "cake": "organic",
    # Residual / general
    "cell phone": "residual",
    "remote": "residual",
}


def category_for(label: str) -> str:
    """Return the waste category slug for a detection label.

    Falls back to ``"unknown"`` if no mapping exists.
    """
    if not label:
        return "unknown"
    return LABEL_TO_CATEGORY.get(label.strip().lower(), "unknown")


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
