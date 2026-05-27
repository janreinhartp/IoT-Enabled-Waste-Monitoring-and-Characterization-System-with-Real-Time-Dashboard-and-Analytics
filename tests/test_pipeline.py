import os
import time

from app.ai.detector import MockDetector
from app.config import AppConfig
from app.core.db import Database
from app.core.pipeline import Pipeline
from app.hardware.mock import MockCamera, MockScale


def build_pipeline(tmp_path):
    cfg = AppConfig()
    cfg.hardware.use_mock = True
    cfg.hardware.scale.sample_rate_hz = 50  # fast for tests
    cfg.events.min_weight_g = 5.0
    cfg.events.stability_window = 4
    cfg.events.stability_g = 0.5
    cfg.events.reset_threshold_g = 2.0
    cfg.storage.images_dir = str(tmp_path / "images")

    db = Database(f"sqlite:///{tmp_path}/test.db")
    db.create_all()

    scale = MockScale()
    camera = MockCamera(width=64, height=48)
    detector = MockDetector(min_confidence=0.0)

    events: list = []
    weights: list = []
    pipeline = Pipeline(
        cfg,
        scale=scale,
        camera=camera,
        detector=detector,
        db=db,
        on_event=lambda rec: events.append(rec),
        on_weight=lambda g: weights.append(g),
    )
    return pipeline, scale, db, events, weights


def test_pipeline_records_event_on_stable_placement(tmp_path):
    pipeline, scale, db, events, weights = build_pipeline(tmp_path)
    pipeline.start()
    try:
        # Drive the mock scale to a stable load
        scale.set_weight(250.0)
        # Wait up to 3 s for at least one event
        deadline = time.time() + 3.0
        while time.time() < deadline and not events:
            time.sleep(0.05)
        assert events, "Pipeline did not record an event in time"
    finally:
        pipeline.stop()

    # With multi-detection, 1 or more events may be stored per placement.
    stored = db.list_events(limit=10)
    assert len(stored) >= 1

    # Total weight across all stored events must equal the placement weight.
    total_weight = sum(e.weight_grams for e in stored)
    assert abs(total_weight - 250.0) < 1.0

    # Every event must have a valid category.
    valid_categories = {"plastic", "paper", "metal", "glass"}
    for e in stored:
        assert e.waste_category in valid_categories

    # Image was saved (all events share the same captured frame path).
    assert events[0].image_path and os.path.isfile(events[0].image_path)

    # Weight callback was called repeatedly
    assert len(weights) > 0
