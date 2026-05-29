"""SQLAlchemy database layer.

Defines the ``WasteEvent`` and ``Category`` tables, exposes a session
factory, and provides query helpers used by both the pipeline and the
web layer.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Iterable, Iterator, List, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
    func,
    select,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Session,
    relationship,
    sessionmaker,
)

from .events import WasteEventRecord


class Base(DeclarativeBase):
    pass


# Supported waste categories. (display_name, slug, color)
DEFAULT_CATEGORIES = [
    ("Plastic", "plastic", "#3b82f6"),
    ("Paper", "paper", "#f59e0b"),
    ("Metal", "metal", "#6b7280"),
    ("Glass", "glass", "#10b981"),
    ("Unknown", "unknown", "#9ca3af"),
]


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    slug = Column(String(32), unique=True, nullable=False)
    name = Column(String(64), nullable=False)
    color = Column(String(16), nullable=False, default="#888888")

    events = relationship("WasteEvent", back_populates="category")


class WasteEvent(Base):
    __tablename__ = "waste_events"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    weight_grams = Column(Float, nullable=False)
    detected_label = Column(String(128), nullable=False, default="unknown")
    category_slug = Column(
        String(32), ForeignKey("categories.slug"), nullable=False, default="unknown"
    )
    confidence = Column(Float, nullable=False, default=0.0)
    image_path = Column(String(255), nullable=True)

    category = relationship("Category", back_populates="events")

    def to_record(self) -> WasteEventRecord:
        return WasteEventRecord(
            id=self.id,
            timestamp=self.timestamp,
            weight_grams=float(self.weight_grams),
            detected_label=self.detected_label,
            waste_category=self.category_slug,
            confidence=float(self.confidence),
            image_path=self.image_path,
        )


class Database:
    """Wraps a SQLAlchemy engine + session factory."""

    def __init__(self, url: str):
        # Ensure parent directory exists for sqlite files
        if url.startswith("sqlite:///"):
            db_path = url.replace("sqlite:///", "", 1)
            parent = os.path.dirname(db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
        self.engine = create_engine(url, future=True)
        self._SessionLocal = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False, future=True
        )

    def create_all(self) -> None:
        Base.metadata.create_all(self.engine)
        self._seed_categories()

    def reset_events(self) -> int:
        """Delete all waste events and their images from disk.

        Returns the number of rows deleted.
        """
        import shutil  # noqa: WPS433

        with self.session() as s:
            events = s.scalars(select(WasteEvent)).all()
            count = len(events)
            for ev in events:
                if ev.image_path and os.path.isfile(ev.image_path):
                    try:
                        os.remove(ev.image_path)
                    except OSError:
                        pass
            s.query(WasteEvent).delete()
            s.commit()
        return count

    def _seed_categories(self) -> None:
        with self.session() as s:
            existing = {c.slug for c in s.scalars(select(Category)).all()}
            for name, slug, color in DEFAULT_CATEGORIES:
                if slug not in existing:
                    s.add(Category(slug=slug, name=name, color=color))
            s.commit()

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self._SessionLocal()
        try:
            yield s
        finally:
            s.close()

    # ---- Query helpers ----

    def insert_event(
        self,
        *,
        weight_grams: float,
        detected_label: str,
        category_slug: str,
        confidence: float,
        image_path: Optional[str],
        timestamp: Optional[datetime] = None,
    ) -> WasteEventRecord:
        with self.session() as s:
            event = WasteEvent(
                timestamp=timestamp or datetime.utcnow(),
                weight_grams=weight_grams,
                detected_label=detected_label,
                category_slug=category_slug,
                confidence=confidence,
                image_path=image_path,
            )
            s.add(event)
            s.commit()
            s.refresh(event)
            return event.to_record()

    def list_events(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        category: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> List[WasteEventRecord]:
        with self.session() as s:
            stmt = select(WasteEvent).order_by(WasteEvent.timestamp.desc())
            if category:
                stmt = stmt.where(WasteEvent.category_slug == category)
            if since:
                stmt = stmt.where(WasteEvent.timestamp >= since)
            if until:
                stmt = stmt.where(WasteEvent.timestamp <= until)
            stmt = stmt.limit(limit).offset(offset)
            return [e.to_record() for e in s.scalars(stmt).all()]

    def list_categories(self) -> List[dict]:
        with self.session() as s:
            return [
                {"slug": c.slug, "name": c.name, "color": c.color}
                for c in s.scalars(select(Category).order_by(Category.name)).all()
            ]

    def summary(
        self, *, since: Optional[datetime] = None
    ) -> dict:
        """Return aggregate stats: per-category counts and weights, totals."""
        with self.session() as s:
            stmt = select(
                WasteEvent.category_slug,
                func.count(WasteEvent.id),
                func.coalesce(func.sum(WasteEvent.weight_grams), 0.0),
            ).group_by(WasteEvent.category_slug)
            if since:
                stmt = stmt.where(WasteEvent.timestamp >= since)
            rows = s.execute(stmt).all()

            per_category = [
                {"category": slug, "count": int(count), "weight_g": float(weight)}
                for slug, count, weight in rows
            ]
            total_count = sum(r["count"] for r in per_category)
            total_weight = sum(r["weight_g"] for r in per_category)
            return {
                "per_category": per_category,
                "total_count": total_count,
                "total_weight_g": total_weight,
            }

    def daily_totals(self, *, days: int = 14) -> List[dict]:
        """Return list of {date, count, weight_g} for the last ``days`` days."""
        since = datetime.utcnow() - timedelta(days=days)
        with self.session() as s:
            # SQLite-friendly date grouping
            day_expr = func.date(WasteEvent.timestamp)
            stmt = (
                select(
                    day_expr.label("day"),
                    func.count(WasteEvent.id),
                    func.coalesce(func.sum(WasteEvent.weight_grams), 0.0),
                )
                .where(WasteEvent.timestamp >= since)
                .group_by(day_expr)
                .order_by(day_expr)
            )
            rows = s.execute(stmt).all()
            return [
                {"date": str(day), "count": int(count), "weight_g": float(weight)}
                for day, count, weight in rows
            ]
