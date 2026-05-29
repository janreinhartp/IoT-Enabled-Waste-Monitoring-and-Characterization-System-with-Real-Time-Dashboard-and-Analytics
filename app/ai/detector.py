"""AI object detection.

Provides:

* :class:`Detector` - abstract interface (``detect_all(frame) -> List[Detection]``)
* :class:`MockDetector` - cycles through fixed labels, useful for dev/tests.
* :class:`TFLiteDetector` - runs a TFLite object-detection model.
* :func:`build_detector` - factory that selects an implementation based on
  the application config.
"""

from __future__ import annotations

import os
import random
from typing import List, Optional, Protocol

import numpy as np

from app.config import AppConfig
from app.core.events import Detection
from app.utils import get_logger

from .labels import category_for, load_labels

log = get_logger(__name__)


class Detector(Protocol):
    def detect_all(self, frame: np.ndarray) -> List[Detection]:
        """Run detection on a BGR frame; return all detections above threshold."""


# ---------------------------------------------------------------------------
# Mock detector
# ---------------------------------------------------------------------------


class MockDetector:
    """Cycles through demo labels and returns 1–2 detections per call."""

    _DEMO = [
        ("bottle", 0.88),
        ("can", 0.81),
        ("book", 0.74),
        ("wine glass", 0.71),
        ("cup", 0.69),
        ("knife", 0.72),
    ]

    def __init__(self, min_confidence: float = 0.0):
        self._min_confidence = min_confidence
        self._i = 0

    def detect_all(self, frame: np.ndarray) -> List[Detection]:
        count = random.randint(1, 2)
        results: List[Detection] = []
        for _ in range(count):
            label, conf = self._DEMO[self._i % len(self._DEMO)]
            self._i += 1
            conf = max(0.0, min(1.0, conf + random.uniform(-0.05, 0.05)))
            if conf < self._min_confidence:
                continue
            cat = category_for(label)
            if cat is not None:
                results.append(Detection(label=label, category=cat, confidence=conf))
        return results

    def preview_all(self, frame: np.ndarray) -> List[dict]:
        """Return all demo detections with no filtering — for debug scans."""
        results: List[dict] = []
        for label, conf in self._DEMO:
            conf = max(0.0, min(1.0, conf + random.uniform(-0.05, 0.05)))
            results.append({"label": label, "confidence": conf, "category": category_for(label)})
        return results


# ---------------------------------------------------------------------------
# TFLite detector
# ---------------------------------------------------------------------------


class TFLiteDetector:
    """Run a TensorFlow Lite object-detection model.

    Designed for EfficientDet-Lite / SSD MobileNet-style models that output
    four tensors: boxes, classes, scores, num_detections.
    """

    def __init__(
        self,
        *,
        model_path: str,
        labels_path: str,
        input_size: int = 320,
        min_confidence: float = 0.4,
    ):
        if not os.path.isfile(model_path):
            raise FileNotFoundError(f"Model not found: {model_path}")
        if not os.path.isfile(labels_path):
            raise FileNotFoundError(f"Labels not found: {labels_path}")

        # Prefer tflite_runtime on the Pi; fall back to ai_edge_litert (the
        # package installed by ai-edge-litert on Python 3.12+), then full TF.
        try:
            from tflite_runtime.interpreter import Interpreter  # type: ignore
        except ImportError:  # pragma: no cover - fallback path
            try:
                from ai_edge_litert.interpreter import Interpreter  # type: ignore
            except ImportError:
                from tensorflow.lite.python.interpreter import Interpreter  # type: ignore

        self._interpreter = Interpreter(model_path=model_path)
        self._interpreter.allocate_tensors()
        self._input_details = self._interpreter.get_input_details()
        self._output_details = self._interpreter.get_output_details()
        self._labels: List[str] = load_labels(labels_path)
        self._input_size = input_size
        self._min_confidence = min_confidence

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_inference(self, frame: np.ndarray):
        """Run the model on *frame* and return (classes_arr, scores_arr).

        Both arrays are 1-D numpy arrays aligned by detection slot.
        Returns ``(None, None)`` if the output tensors could not be parsed.
        """
        import cv2  # noqa: WPS433

        resized = cv2.resize(frame, (self._input_size, self._input_size))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        input_tensor = np.expand_dims(rgb, axis=0).astype(self._input_details[0]["dtype"])
        self._interpreter.set_tensor(self._input_details[0]["index"], input_tensor)
        self._interpreter.invoke()

        # EfficientDet-Lite / SSD MobileNet TFLite output layout (4 tensors):
        #   [0] boxes      float32 [1, N, 4]
        #   [1] class_ids  float32 [1, N]
        #   [2] scores     float32 [1, N]
        #   [3] count      float32 [1]
        # Use output tensor names to locate scores and classes robustly.
        scores_arr: Optional[np.ndarray] = None
        classes_arr: Optional[np.ndarray] = None
        for detail in self._output_details:
            name = detail.get("name", "").lower()
            tensor = np.squeeze(self._interpreter.get_tensor(detail["index"]))
            if tensor.ndim != 1:
                continue
            if "score" in name or "confidence" in name:
                scores_arr = tensor
            elif "class" in name or "category" in name or "label" in name:
                classes_arr = tensor

        # Fall back to positional order if names were not informative.
        if scores_arr is None or classes_arr is None:
            outs = [
                np.squeeze(self._interpreter.get_tensor(d["index"]))
                for d in self._output_details
            ]
            one_d = [a for a in outs if a.ndim == 1]
            if len(one_d) >= 2:
                classes_arr = one_d[0]   # first 1-D output = class IDs
                scores_arr = one_d[1]    # second 1-D output = scores

        return classes_arr, scores_arr

    # ------------------------------------------------------------------
    # Public detection methods
    # ------------------------------------------------------------------

    def detect_all(self, frame: np.ndarray) -> List[Detection]:
        classes_arr, scores_arr = self._run_inference(frame)
        if scores_arr is None or classes_arr is None:
            log.warning("Could not parse TFLite outputs; no detections emitted")
            return []

        results: List[Detection] = []
        for i in range(len(scores_arr)):
            score = float(scores_arr[i])
            if score < self._min_confidence:
                continue
            class_idx = int(classes_arr[i])
            label = (
                self._labels[class_idx]
                if 0 <= class_idx < len(self._labels)
                else f"class_{class_idx}"
            )
            cat = category_for(label)
            if cat is not None:
                results.append(Detection(label=label, category=cat, confidence=score))
            else:
                log.info("Detected '%s' (%.2f) — not mapped to a waste category", label, score)
        return results

    def preview_all(self, frame: np.ndarray) -> List[dict]:
        """Return ALL model predictions above a low threshold (0.10) as raw dicts.

        Unlike :meth:`detect_all` this does **not** filter by waste category, so
        you can see exactly what the model is detecting (even if it's not yet in
        ``LABEL_TO_CATEGORY``).  Used by the dashboard "What's here?" scan.
        ``category`` is ``None`` when the label has no waste-category mapping.
        """
        classes_arr, scores_arr = self._run_inference(frame)
        if scores_arr is None or classes_arr is None:
            return []

        results: List[dict] = []
        for i in range(len(scores_arr)):
            score = float(scores_arr[i])
            if score < 0.10:
                continue
            class_idx = int(classes_arr[i])
            label = (
                self._labels[class_idx]
                if 0 <= class_idx < len(self._labels)
                else f"class_{class_idx}"
            )
            results.append({"label": label, "confidence": score, "category": category_for(label)})
        return results


# ---------------------------------------------------------------------------
# TFLite image-classification backend (Google Teachable Machine / MobileNet)
# ---------------------------------------------------------------------------


class TFLiteClassifier:
    """Run a TensorFlow Lite image-classification model.

    Works with Google Teachable Machine TFLite exports and any other
    single-label image-classification model.

    Expected model format:
    - Input:  [1, H, W, 3]  uint8 *or* float32
    - Output: [1, num_classes] *or* [num_classes]  float32 probabilities

    The top-1 prediction is returned as a single :class:`Detection` when
    confidence >= ``min_confidence`` *and* the label maps to a known waste
    category via :func:`~app.ai.labels.category_for`.

    For Teachable Machine models, name your classes exactly as the category
    slugs (e.g. ``plastic``, ``paper``, ``metal``, ``glass``, ``organic``)
    and they will be recognised automatically.
    """

    def __init__(
        self,
        *,
        model_path: str,
        labels_path: str,
        input_size: int = 224,
        min_confidence: float = 0.4,
    ):
        if not os.path.isfile(model_path):
            raise FileNotFoundError(f"Model not found: {model_path}")
        if not os.path.isfile(labels_path):
            raise FileNotFoundError(f"Labels not found: {labels_path}")

        try:
            from tflite_runtime.interpreter import Interpreter  # type: ignore
        except ImportError:  # pragma: no cover
            try:
                from ai_edge_litert.interpreter import Interpreter  # type: ignore
            except ImportError:
                from tensorflow.lite.python.interpreter import Interpreter  # type: ignore

        self._interpreter = Interpreter(model_path=model_path)
        self._interpreter.allocate_tensors()
        self._input_details = self._interpreter.get_input_details()
        self._output_details = self._interpreter.get_output_details()
        self._labels: List[str] = load_labels(labels_path)
        self._input_size = input_size
        self._min_confidence = min_confidence
        self._input_dtype = self._input_details[0]["dtype"]

    def detect_all(self, frame: np.ndarray) -> List[Detection]:
        import cv2  # noqa: WPS433

        resized = cv2.resize(frame, (self._input_size, self._input_size))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)

        if self._input_dtype == np.uint8:
            input_tensor = np.expand_dims(rgb, axis=0).astype(np.uint8)
        else:
            # float32 — normalise to [0, 1] (standard for Teachable Machine)
            input_tensor = np.expand_dims(rgb.astype(np.float32) / 255.0, axis=0)

        self._interpreter.set_tensor(self._input_details[0]["index"], input_tensor)
        self._interpreter.invoke()

        probs = np.squeeze(
            self._interpreter.get_tensor(self._output_details[0]["index"])
        )
        top_idx = int(np.argmax(probs))
        confidence = float(probs[top_idx])

        if confidence < self._min_confidence:
            log.info("Top prediction '%s' confidence %.2f below threshold %.2f",
                     self._labels[top_idx] if 0 <= top_idx < len(self._labels) else f"class_{top_idx}",
                     confidence, self._min_confidence)
            return []

        label = (
            self._labels[top_idx]
            if 0 <= top_idx < len(self._labels)
            else f"class_{top_idx}"
        )
        cat = category_for(label)
        if cat is None:
            log.info("Classified as '%s' (%.2f) — not mapped to a waste category", label, confidence)
            return []

        return [Detection(label=label, category=cat, confidence=confidence)]

    def preview_all(self, frame: np.ndarray) -> List[dict]:
        """Return the top-5 class predictions as raw dicts (no category filter).

        Used by the dashboard debug scan.  ``category`` is ``None`` when the
        label has no waste-category mapping.
        """
        import cv2  # noqa: WPS433

        resized = cv2.resize(frame, (self._input_size, self._input_size))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)

        if self._input_dtype == np.uint8:
            input_tensor = np.expand_dims(rgb, axis=0).astype(np.uint8)
        else:
            input_tensor = np.expand_dims(rgb.astype(np.float32) / 255.0, axis=0)

        self._interpreter.set_tensor(self._input_details[0]["index"], input_tensor)
        self._interpreter.invoke()

        probs = np.squeeze(
            self._interpreter.get_tensor(self._output_details[0]["index"])
        )
        top_indices = np.argsort(probs)[::-1][:5]  # top-5
        results: List[dict] = []
        for idx in top_indices:
            conf = float(probs[idx])
            if conf < 0.05:
                break
            label = self._labels[idx] if 0 <= idx < len(self._labels) else f"class_{idx}"
            results.append({"label": label, "confidence": conf, "category": category_for(label)})
        return results


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_detector(cfg: AppConfig) -> Detector:
    backend = (cfg.ai.backend or "mock").lower()
    if backend == "mock":
        log.info("Using MockDetector")
        return MockDetector(min_confidence=cfg.ai.min_confidence)
    if backend == "tflite":
        log.info("Using TFLiteDetector model=%s", cfg.ai.model_path)
        return TFLiteDetector(
            model_path=cfg.ai.model_path,
            labels_path=cfg.ai.labels_path,
            input_size=cfg.ai.input_size,
            min_confidence=cfg.ai.min_confidence,
        )
    if backend == "classification":
        log.info("Using TFLiteClassifier model=%s", cfg.ai.model_path)
        return TFLiteClassifier(
            model_path=cfg.ai.model_path,
            labels_path=cfg.ai.labels_path,
            input_size=cfg.ai.input_size,
            min_confidence=cfg.ai.min_confidence,
        )
    raise ValueError(f"Unknown AI backend: {backend!r}")
