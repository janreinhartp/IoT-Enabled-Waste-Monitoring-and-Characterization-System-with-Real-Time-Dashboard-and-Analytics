import numpy as np
import pytest

from app.ai.detector import MockDetector
from app.ai.labels import category_for


def test_label_to_category_mapping():
    assert category_for("bottle") == "plastic"
    assert category_for("can") == "metal"
    assert category_for("book") == "paper"
    assert category_for("wine glass") == "glass"
    # Labels removed from the 4-category system return None
    assert category_for("banana") is None
    assert category_for("unknown-thing") is None
    assert category_for("") is None


def test_mock_detector_cycles():
    det = MockDetector(min_confidence=0.0)
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    labels = set()
    for _ in range(20):
        detections = det.detect_all(frame)
        assert isinstance(detections, list)
        for d in detections:
            assert 0.0 <= d.confidence <= 1.0
            assert d.category in {"plastic", "paper", "metal", "glass"}
            labels.add(d.label)
    # Cycled through more than one label
    assert len(labels) > 1


def test_mock_detector_respects_min_confidence():
    det = MockDetector(min_confidence=1.5)  # impossible to satisfy
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    # Returns empty list when no detection meets the threshold
    assert det.detect_all(frame) == []
