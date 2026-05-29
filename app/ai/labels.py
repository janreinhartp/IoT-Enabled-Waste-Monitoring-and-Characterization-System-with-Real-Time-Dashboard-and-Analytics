"""Mapping from object-detection / classification labels to waste categories.

Supported categories: ``plastic``, ``paper``, ``metal``, ``glass``, ``organic``.

Used by two backends:
* **tflite** (EfficientDet-Lite0 COCO detection) – labels are COCO object names
  such as ``"bottle"`` or ``"can"`` that get mapped here.
* **classification** (Google Teachable Machine or any image classifier) – label
  the model's classes directly as ``"plastic"``, ``"paper"``, ``"metal"``,
  ``"glass"``, or ``"organic"`` and they are mapped automatically.

Labels that do not map to a supported category return ``None`` and are
ignored by the pipeline.
"""

from __future__ import annotations

from typing import Dict, List, Optional

# Detection-label (lowercase) -> waste category slug
LABEL_TO_CATEGORY: Dict[str, str] = {
    # ── Direct category slug matches (classification models) ─────────────────
    "plastic": "plastic",
    "paper": "paper",
    "metal": "metal",
    "glass": "glass",
    "organic": "organic",
    "cardboard": "paper",   # TrashNet / Teachable Machine common class name

    # ── Plastic ──────────────────────────────────────────────────────────────
    "bottle": "plastic",
    "cup": "plastic",
    "bowl": "plastic",
    "plastic bag": "plastic",
    "bag": "plastic",
    "container": "plastic",
    "straw": "plastic",
    "toothbrush": "plastic",
    "hair drier": "plastic",
    "remote": "plastic",
    "cell phone": "plastic",
    "keyboard": "plastic",
    "mouse": "plastic",

    # ── Paper / cardboard ────────────────────────────────────────────────────
    "book": "paper",
    "newspaper": "paper",
    "magazine": "paper",
    "box": "paper",

    # ── Metal ────────────────────────────────────────────────────────────────
    "can": "metal",
    "fork": "metal",
    "knife": "metal",
    "spoon": "metal",
    "scissors": "metal",
    "tin can": "metal",
    "tin": "metal",
    "aluminum can": "metal",

    # ── Glass ────────────────────────────────────────────────────────────────
    "wine glass": "glass",
    "vase": "glass",
    "jar": "glass",
    "glass bottle": "glass",
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
