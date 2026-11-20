import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Jurisdiction(Base):
    """A government that can impose VPR rules: a state, a county, or a city/town."""

    __tablename__ = "vpr_jurisdictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # e.g. "state|CO", "county|CO|adams", "city|CO|aurora"
    key: Mapped[str] = mapped_column(String(200), unique=True)
    level: Mapped[str] = mapped_column(String(10))  # state | county | city
    state_code: Mapped[str] = mapped_column(String(2), index=True)
    name: Mapped[str] = mapped_column(String(120))
    display_name: Mapped[str] = mapped_column(String(160))  # "City of Aurora"
    geoid: Mapped[str | None] = mapped_column(String(20))  # Census GEOID when known
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    rules: Mapped[list["VprRule"]] = relationship(back_populates="jurisdiction")


class VprRule(Base):
    """One research result for a jurisdiction. Rows are append-only so history is kept;
    the newest row per jurisdiction is the current rule."""

    __tablename__ = "vpr_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    jurisdiction_id: Mapped[int] = mapped_column(ForeignKey("vpr_jurisdictions.id"))
    researched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(20))  # ai_researched | human_verified | error
    model: Mapped[str | None] = mapped_column(String(60))

    # Promoted fields (also inside `data`) so the future nationwide DB can be queried.
    vacant_required: Mapped[str | None] = mapped_column(String(10))  # Yes | No | Unclear
    foreclosure_required: Mapped[str | None] = mapped_column(String(10))
    ordinance_url: Mapped[str | None] = mapped_column(Text)
    form_url: Mapped[str | None] = mapped_column(Text)
    registration_fee: Mapped[str | None] = mapped_column(Text)

    data: Mapped[dict | None] = mapped_column(JSONB)  # full structured research output
    sources: Mapped[list | None] = mapped_column(JSONB)  # citations returned by web search
    link_checks: Mapped[dict | None] = mapped_column(JSONB)  # url -> {ok, status}
    error: Mapped[str | None] = mapped_column(Text)

    jurisdiction: Mapped[Jurisdiction] = relationship(back_populates="rules")

    __table_args__ = (Index("ix_vpr_rules_jurisdiction_time", "jurisdiction_id", "researched_at"),)


class Batch(Base):
    """One bulk upload. `rows` keeps every data row of the file in order:
    {"row": <sheet row number>, "input": {...} | None, "extra": {...}, "lookup_id": str | None, "error": str | None}.
    Rows that failed validation have an `error` and no lookup."""

    __tablename__ = "vpr_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    extra_columns: Mapped[list] = mapped_column(JSONB, default=list)  # other columns of the file, kept for export
    rows: Mapped[list] = mapped_column(JSONB)


class Lookup(Base):
    """One address lookup requested from the UI."""

    __tablename__ = "vpr_lookups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|running|done|error
    progress: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    force_refresh: Mapped[bool] = mapped_column(default=False)

    input: Mapped[dict] = mapped_column(JSONB)
    geocode: Mapped[dict | None] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB)
