from datetime import datetime

from app.core.db import Database


def make_db(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/test.db")
    db.create_all()
    return db


def test_seed_categories(tmp_path):
    db = make_db(tmp_path)
    slugs = {c["slug"] for c in db.list_categories()}
    assert {"plastic", "paper", "metal", "glass"} <= slugs
    # Removed categories must not be seeded
    assert "organic" not in slugs
    assert "unknown" not in slugs


def test_insert_and_list_events(tmp_path):
    db = make_db(tmp_path)
    rec = db.insert_event(
        weight_grams=123.4,
        detected_label="bottle",
        category_slug="plastic",
        confidence=0.91,
        image_path=None,
    )
    assert rec.id > 0
    assert rec.detected_label == "bottle"

    events = db.list_events(limit=10)
    assert len(events) == 1
    assert events[0].weight_grams == 123.4


def test_summary_and_filtering(tmp_path):
    db = make_db(tmp_path)
    db.insert_event(
        weight_grams=100, detected_label="bottle", category_slug="plastic",
        confidence=0.9, image_path=None,
    )
    db.insert_event(
        weight_grams=50, detected_label="can", category_slug="metal",
        confidence=0.8, image_path=None,
    )
    db.insert_event(
        weight_grams=200, detected_label="bottle", category_slug="plastic",
        confidence=0.7, image_path=None,
    )

    summary = db.summary()
    assert summary["total_count"] == 3
    assert summary["total_weight_g"] == 350.0
    per = {row["category"]: row for row in summary["per_category"]}
    assert per["plastic"]["count"] == 2
    assert per["plastic"]["weight_g"] == 300.0
    assert per["metal"]["count"] == 1

    plastic_only = db.list_events(category="plastic")
    assert len(plastic_only) == 2
    assert all(e.waste_category == "plastic" for e in plastic_only)


def test_daily_totals(tmp_path):
    db = make_db(tmp_path)
    db.insert_event(
        weight_grams=10, detected_label="x", category_slug="plastic",
        confidence=0.5, image_path=None, timestamp=datetime.utcnow(),
    )
    days = db.daily_totals(days=7)
    assert len(days) >= 1
    assert days[-1]["count"] >= 1
