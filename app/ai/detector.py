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

    def detect_all(self, frame: np.ndarray) -> List[Detection]:
        import cv2  # noqa: WPS433

        resized = cv2.resize(frame, (self._input_size, self._input_size))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        input_tensor = np.expand_dims(rgb, axis=0).astype(self._input_details[0]["dtype"])
        self._interpreter.set_tensor(self._input_details[0]["index"], input_tensor)
        self._interpreter.invoke()

        # EfficientDet-Lite output order: boxes(0), classes(1), scores(2), num(3)
        outs = [self._interpreter.get_tensor(d["index"]) for d in self._output_details]
        scores = None
        classes = None
        for arr in outs:
            sq = np.squeeze(arr)
            if sq.ndim == 1 and scores is None and 0.0 <= float(sq.max(initial=0.0)) <= 1.0:
                if classes is None:
                    scores = sq
                    continue
            if sq.ndim == 1 and classes is None and scores is not None:
                classes = sq

        if scores is None or classes is None:
            log.warning("Could not parse TFLite outputs; no detections emitted")
            return []

        results: List[Detection] = []
        for i in range(len(scores)):
            score = float(scores[i])
            if score < self._min_confidence:
                continue
            class_idx = int(classes[i])
            label = (
                self._labels[class_idx]
                if 0 <= class_idx < len(self._labels)
                else f"class_{class_idx}"
            )
            cat = category_for(label)
            if cat is not None:
                results.append(Detection(label=label, category=cat, confidence=score))
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
    raise ValueError(f"Unknown AI backend: {backend!r}")
