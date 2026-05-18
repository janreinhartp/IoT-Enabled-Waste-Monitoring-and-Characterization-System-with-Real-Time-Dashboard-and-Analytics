from app.hardware.scale import StableEventDetector


def make_detector():
    return StableEventDetector(
        min_weight_g=5.0,
        stability_window=4,
        stability_g=0.5,
        reset_threshold_g=2.0,
    )


def test_stable_event_fires_after_stabilization():
    det = make_detector()
    # Empty scale - no event
    for _ in range(3):
        assert det.push(0.0) is None
    # Item placed and stable. Window=4, so we need 4 consecutive stable samples.
    assert det.push(100.0) is None  # window: [100.0]
    assert det.push(100.2) is None  # [100.0, 100.2]
    assert det.push(100.1) is None  # [100.0, 100.2, 100.1]
    event = det.push(100.05)        # [100.0, 100.2, 100.1, 100.05] -> stddev tiny
    assert event is not None
    assert 99 < event.weight_grams < 101
    assert det.state == "cooldown"


def test_no_event_when_unstable():
    det = make_detector()
    det.push(0.0)
    det.push(50.0)
    # Window of 4 with high variance -> no event
    for v in [50.0, 80.0, 30.0, 90.0, 40.0]:
        assert det.push(v) is None


def test_below_threshold_does_not_emit():
    det = make_detector()
    for _ in range(10):
        assert det.push(2.0) is None  # below min_weight_g
    assert det.state == "idle"


def test_cooldown_until_reset():
    det = make_detector()
    # Force a stable event
    det.push(0.0)
    for v in [100.0, 100.0, 100.0, 100.0]:
        out = det.push(v)
    assert out is not None
    # Still cooled down: a new stable load should not fire
    for v in [100.0, 100.0, 100.0, 100.0]:
        assert det.push(v) is None
    # Drop below reset_threshold
    assert det.push(1.0) is None
    assert det.state == "idle"
    # Now a new stable load fires
    det.push(0.0)
    for v in [120.0, 120.0, 120.0, 120.0]:
        out = det.push(v)
    assert out is not None


def test_item_lifted_before_stabilizing_resets():
    det = make_detector()
    det.push(0.0)
    det.push(50.0)
    det.push(50.0)
    # Item removed before window fills
    assert det.push(0.0) is None
    assert det.state == "idle"
