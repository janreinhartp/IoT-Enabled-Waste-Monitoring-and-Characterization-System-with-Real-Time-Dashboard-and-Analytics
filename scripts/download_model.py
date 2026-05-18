"""Download a small TFLite object-detection model (EfficientDet-Lite0) and labels.

Usage:
    python -m scripts.download_model

Downloads into ``app/ai/models/`` so the paths in ``config.example.yaml``
work out of the box.
"""

from __future__ import annotations

import os
import sys
import urllib.request

MODEL_URL = (
    "https://storage.googleapis.com/download.tensorflow.org/models/"
    "tflite/task_library/object_detection/rpi/lite-model_efficientdet_lite0_detection_metadata_1.tflite"
)
MODEL_DEST = "app/ai/models/efficientdet_lite0.tflite"

LABELS_URL = (
    "https://raw.githubusercontent.com/google-coral/test_data/master/coco_labels.txt"
)
LABELS_DEST = "app/ai/models/coco_labels.txt"


def _download(url: str, dest: str) -> None:
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.isfile(dest):
        print(f"  already exists: {dest}")
        return
    print(f"  downloading {url}")
    with urllib.request.urlopen(url, timeout=60) as resp, open(dest, "wb") as fp:
        fp.write(resp.read())
    print(f"  saved {dest} ({os.path.getsize(dest)} bytes)")


def main() -> int:
    print("Fetching TFLite model + labels…")
    try:
        _download(MODEL_URL, MODEL_DEST)
        _download(LABELS_URL, LABELS_DEST)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("Done. Set ai.backend: tflite in config.yaml to use.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
