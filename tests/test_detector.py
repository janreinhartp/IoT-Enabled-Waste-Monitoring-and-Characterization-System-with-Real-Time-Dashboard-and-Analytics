import numpy as np

from app.ai.detector import MockDetector
from app.ai.labels import category_for


def test_label_to_category_mapping():
    assert category_for("bottle") == "plastic"
    assert category_for("Banana") == "organic"
    assert category_for("can") == "metal"
    assert category_for("unknown-thing") == "unknown"
    assert category_for("") == "unknown"


def test_mock_detector_cycles():
    det = MockDetector(min_confidence=0.0)
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    labels = set()
    for _ in range(10):
        d = det.detect(frame)
        assert d is not None
        assert 0.0 <= d.confidence <= 1.0
        labels.add(d.label)
    # Cycled through more than one label
    assert len(labels) > 1


def test_mock_detector_respects_min_confidence():
    det = MockDetector(min_confidence=1.5)  # impossible to satisfy
    frame = np.zeros((10, 10, 3), dtype=np.uint8)
    assert det.detect(frame) is None
