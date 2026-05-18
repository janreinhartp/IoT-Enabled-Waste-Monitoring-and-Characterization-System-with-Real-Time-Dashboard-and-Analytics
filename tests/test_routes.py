from app.config import AppConfig
from app.core.db import Database
from app.web.server import create_app


def _make_app(tmp_path):
    cfg = AppConfig()
    cfg.database.url = f"sqlite:///{tmp_path}/test.db"
    cfg.storage.images_dir = str(tmp_path / "images")
    db = Database(cfg.database.url)
    db.create_all()
    # Seed an event so endpoints have something to return
    db.insert_event(
        weight_grams=42.0,
        detected_label="bottle",
        category_slug="plastic",
        confidence=0.88,
        image_path=None,
    )
    app, _socketio = create_app(cfg, db, async_mode="threading")
    app.config["TESTING"] = True
    return app, db


def test_dashboard_renders(tmp_path):
    app, _ = _make_app(tmp_path)
    client = app.test_client()
    r = client.get("/")
    assert r.status_code == 200
    assert b"Waste Monitor" in r.data
    assert b"bottle" in r.data


def test_analytics_renders(tmp_path):
    app, _ = _make_app(tmp_path)
    client = app.test_client()
    r = client.get("/analytics")
    assert r.status_code == 200
    assert b"Analytics" in r.data or b"Weight by Category" in r.data


def test_api_events_returns_json(tmp_path):
    app, _ = _make_app(tmp_path)
    client = app.test_client()
    r = client.get("/api/events")
    assert r.status_code == 200
    data = r.get_json()
    assert isinstance(data, list) and len(data) == 1
    assert data[0]["detected_label"] == "bottle"
    assert data[0]["waste_category"] == "plastic"


def test_api_summary(tmp_path):
    app, _ = _make_app(tmp_path)
    client = app.test_client()
    r = client.get("/api/summary")
    assert r.status_code == 200
    data = r.get_json()
    assert data["total_count"] == 1
    assert data["total_weight_g"] == 42.0


def test_api_categories(tmp_path):
    app, _ = _make_app(tmp_path)
    client = app.test_client()
    r = client.get("/api/categories")
    assert r.status_code == 200
    slugs = {c["slug"] for c in r.get_json()}
    assert "plastic" in slugs


def test_api_events_csv(tmp_path):
    app, _ = _make_app(tmp_path)
    client = app.test_client()
    r = client.get("/api/events.csv")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert body.startswith("id,timestamp,weight_grams")
    assert "bottle" in body


def test_image_endpoint_404_when_missing(tmp_path):
    app, _ = _make_app(tmp_path)
    client = app.test_client()
    # Event id 1 exists but has no image_path
    r = client.get("/images/1")
    assert r.status_code == 404
    r = client.get("/images/999")
    assert r.status_code == 404
