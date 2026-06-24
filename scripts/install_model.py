"""Install the AI model into app/ai/models/.

Usage (run from the project root):
    python -m scripts.install_model

How it works
------------
1.  Looks for ``.tflite`` and ``.txt`` files in the ``models/`` directory at
    the repository root — the bundled model that ships with the repo (tracked
    by git).
2.  Copies every file found there into ``app/ai/models/`` (the runtime
    location read by the app, intentionally excluded from git via .gitignore).
3.  If ``models/`` contains no model files (e.g. the model was not yet added
    to the repo) the script falls back to downloading EfficientDet-Lite0 from
    TensorFlow Hub — identical to the previous ``download_model`` script.

Adding your own model to the repo
----------------------------------
Drop your ``.tflite`` and matching label ``.txt`` file into ``models/`` and
commit them.  Anyone who clones the repo can then run::

    python -m scripts.install_model

to have the files placed in the correct runtime location automatically.
Then point ``config.yaml`` at the installed path::

    ai:
      backend: tflite
      model_path: app/ai/models/<your_model>.tflite
      labels_path: app/ai/models/<your_labels>.txt
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent   # repo root
_SOURCE_DIR = _ROOT / "models"                   # tracked by git
_DEST_DIR = _ROOT / "app" / "ai" / "models"     # runtime location (gitignored)

# Fallback: download EfficientDet-Lite0 when models/ is empty
_FALLBACK: list[tuple[str, str]] = [
    (
        "https://storage.googleapis.com/download.tensorflow.org/models/"
        "tflite/task_library/object_detection/rpi/"
        "lite-model_efficientdet_lite0_detection_metadata_1.tflite",
        "efficientdet_lite0.tflite",
    ),
    (
        "https://raw.githubusercontent.com/google-coral/test_data/master/coco_labels.txt",
        "coco_labels.txt",
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _copy_bundled() -> list[Path]:
    """Copy .tflite and .txt files from models/ → app/ai/models/.

    Returns the list of destination paths that were written.
    """
    _DEST_DIR.mkdir(parents=True, exist_ok=True)
    sources = sorted(
        list(_SOURCE_DIR.glob("*.tflite")) + list(_SOURCE_DIR.glob("*.txt"))
    )
    written: list[Path] = []
    for src in sources:
        dest = _DEST_DIR / src.name
        shutil.copy2(src, dest)
        print(f"  copied  {src.relative_to(_ROOT)}  →  {dest.relative_to(_ROOT)}")
        written.append(dest)
    return written


def _download(url: str, name: str) -> None:
    import urllib.request

    dest = _DEST_DIR / name
    if dest.is_file():
        print(f"  already exists: {dest.relative_to(_ROOT)}")
        return
    print(f"  downloading {url}")
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310
        data = resp.read()
    _DEST_DIR.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    print(f"  saved {dest.relative_to(_ROOT)} ({len(data):,} bytes)")


def _fallback_download() -> None:
    """Download the default EfficientDet-Lite0 model when no bundled model exists."""
    print(
        "No model files found in models/ — "
        "downloading EfficientDet-Lite0 from TensorFlow Hub …"
    )
    for url, name in _FALLBACK:
        _download(url, name)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    print(f"Installing AI model files into {_DEST_DIR.relative_to(_ROOT)} …\n")

    # ── Step 1: copy bundled models from the repo ─────────────────────────
    if _SOURCE_DIR.is_dir():
        copied = _copy_bundled()
        if copied:
            print(f"\nDone — {len(copied)} file(s) installed.")
            return 0

    # ── Step 2: fall back to downloading when models/ is empty ───────────
    try:
        _fallback_download()
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1

    print(
        "\nDone. Set  ai.backend: tflite  in config.yaml to use the model.\n"
        "Tip: to bundle the model in the repo, place the .tflite and label\n"
        "     .txt files in the models/ directory and commit them."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
