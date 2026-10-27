"""Registry storage: parts, needs, lessons and fit reports. SQLite under $PARTSMITH_HOME by default, Postgres via DATABASE_URL.

Parts are stored as their full `PartRecord` JSON plus a few indexed columns for search and sorting.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from partsmith_schemas import Need, PartRecord
from sqlalchemy import Boolean, Float, Integer, String, Text, create_engine, func, or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from services.common.paths import home


class Base(DeclarativeBase):
    pass


class PartRow(Base):
    __tablename__ = "parts"
    slug: Mapped[str] = mapped_column(String(120), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(200))
    family: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    origin: Mapped[str] = mapped_column(String(24), index=True)
    verified: Mapped[bool] = mapped_column(Boolean, index=True)
    max_error_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    search_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[float] = mapped_column(Float, index=True)
    record: Mapped[str] = mapped_column(Text)


class NeedRow(Base):
    __tablename__ = "needs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    query: Mapped[str] = mapped_column(String(300), index=True)
    votes: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[float] = mapped_column(Float)


class LessonRow(Base):
    __tablename__ = "lessons"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    scope: Mapped[str] = mapped_column(String(32), index=True)  # "global" or a family
    rule: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(16), default="candidate", index=True)  # candidate | promoted | rejected
    promoted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[float] = mapped_column(Float)


class FitReportRow(Base):
    __tablename__ = "fit_reports"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # screen_fit | print
    result: Mapped[str] = mapped_column(String(16))  # fits | tight | loose | pass | fail
    data: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[float] = mapped_column(Float)


def _url() -> str:
    return os.environ.get("DATABASE_URL") or f"sqlite:///{home() / 'partsmith.db'}"


class Registry:
    def __init__(self, url: str | None = None) -> None:
        self.url = url or _url()
        kwargs: dict[str, Any] = {"connect_args": {"check_same_thread": False}} if self.url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(self.url, **kwargs)
        Base.metadata.create_all(self.engine)
        self._session = sessionmaker(self.engine, expire_on_commit=False)
        self._lock = threading.Lock()

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self._session() as s, s.begin():
            yield s

    # ---- parts -------------------------------------------------------------------------------------------------------
    def upsert_part(self, part: PartRecord) -> None:
        v = part.verification
        row = PartRow(
            slug=part.slug,
            id=part.id,
            title=part.title,
            family=part.family.value,
            status=part.status,
            origin=part.provenance.origin.value,
            verified=bool(v and v.verified),
            max_error_mm=v.max_error_mm if v else None,
            search_text=" ".join([part.title, part.family.value, part.summary, " ".join(part.tags), part.slug]).lower(),
            created_at=part.created_at or time.time(),
            record=part.model_dump_json(),
        )
        with self._lock, self.session() as s:
            s.merge(row)

    def get_part(self, slug: str) -> PartRecord | None:
        with self.session() as s:
            row = s.get(PartRow, slug)
            return PartRecord.model_validate_json(row.record) if row else None

    def slugs(self) -> list[str]:
        with self.session() as s:
            return list(s.scalars(select(PartRow.slug).order_by(PartRow.slug)))

    def delete_part(self, slug: str) -> None:
        with self._lock, self.session() as s:
            row = s.get(PartRow, slug)
            if row:
                s.delete(row)

    def search(
        self,
        q: str = "",
        *,
        family: str | None = None,
        verified: bool | None = None,
        origin: str | None = None,
        sort: str = "relevance",
        cursor: int = 0,
        limit: int = 24,
    ) -> tuple[list[PartRecord], int]:
        """Token search over title/family/tags/summary with numeric boosting ("cooler wheel 32 mm" prefers Ø≈32 parts)."""
        tokens = [
            t for t in re.findall(r"[a-z]+", q.lower()) if len(t) > 1 and t not in {"mm", "for", "the", "and", "with"}
        ]
        numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", q)]
        with self.session() as s:
            stmt = select(PartRow)
            if family:
                stmt = stmt.where(PartRow.family == family)
            if verified is not None:
                stmt = stmt.where(PartRow.verified == verified)
            if origin:
                stmt = stmt.where(PartRow.origin == origin)
            if tokens:
                stmt = stmt.where(or_(*[PartRow.search_text.contains(t) for t in tokens]))
            rows = list(s.scalars(stmt))
        parts = [PartRecord.model_validate_json(r.record) for r in rows]
        if sort == "newest":
            parts.sort(key=lambda p: p.created_at, reverse=True)
        elif sort == "error":
            parts.sort(
                key=lambda p: (
                    p.verification.max_error_mm if p.verification and p.verification.max_error_mm is not None else 1e9
                )
            )
        elif sort == "title":
            parts.sort(key=lambda p: p.title.lower())
        else:
            parts.sort(key=lambda p: _score(p, tokens, numbers), reverse=True)
        return parts[cursor : cursor + limit], len(parts)

    def families(self) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = s.execute(
                select(PartRow.family, func.count(), func.sum(func.cast(PartRow.verified, Integer))).group_by(
                    PartRow.family
                )
            ).all()
        return [{"family": f, "count": int(c), "verified": int(v or 0)} for f, c, v in rows]

    def stats(self) -> dict[str, Any]:
        with self.session() as s:
            total = s.scalar(select(func.count()).select_from(PartRow)) or 0
            verified = s.scalar(select(func.count()).select_from(PartRow).where(PartRow.verified.is_(True))) or 0
            by_origin = dict(s.execute(select(PartRow.origin, func.count()).group_by(PartRow.origin)).all())
            records = list(s.scalars(select(PartRow.record)))
        grams = sum((json.loads(r).get("facts") or {}).get("mass_g_pla", 0.0) for r in records)
        return {
            "parts": int(total),
            "verified": int(verified),
            "synthetic": int(by_origin.get("synthetic", 0)),
            "real": int(by_origin.get("real", 0)),
            "reference_object": int(by_origin.get("reference_object", 0)),
            "grams_pla": round(float(grams), 1),
        }

    # ---- needs -------------------------------------------------------------------------------------------------------
    def add_need(self, query: str) -> Need:
        query = query.strip()[:300]
        with self._lock, self.session() as s:
            existing = s.scalars(select(NeedRow).where(func.lower(NeedRow.query) == query.lower())).first()
            if existing:
                existing.votes += 1
                row = existing
            else:
                row = NeedRow(
                    id="n_" + secrets.token_hex(5), query=query, votes=1, status="open", created_at=time.time()
                )
                s.add(row)
            return Need(id=row.id, query=row.query, votes=row.votes, status=row.status, created_at=row.created_at)

    def needs(self, limit: int = 50) -> list[Need]:
        with self.session() as s:
            rows = s.scalars(select(NeedRow).order_by(NeedRow.votes.desc(), NeedRow.created_at.desc()).limit(limit))
            return [Need(id=r.id, query=r.query, votes=r.votes, status=r.status, created_at=r.created_at) for r in rows]

    # ---- lessons -----------------------------------------------------------------------------------------------------
    def add_lesson(self, scope: str, rule: str, evidence: dict[str, Any]) -> str:
        lid = "l_" + secrets.token_hex(5)
        with self._lock, self.session() as s:
            s.add(
                LessonRow(
                    id=lid,
                    scope=scope,
                    rule=rule,
                    evidence=json.dumps(evidence),
                    status="candidate",
                    created_at=time.time(),
                )
            )
        return lid

    def set_lesson_status(self, lid: str, status: str, by: str) -> None:
        with self._lock, self.session() as s:
            row = s.get(LessonRow, lid)
            if row is None:
                raise KeyError(lid)
            row.status = status
            row.promoted_by = by

    def lessons(self, scope: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        with self.session() as s:
            stmt = select(LessonRow)
            if scope:
                stmt = stmt.where(or_(LessonRow.scope == scope, LessonRow.scope == "global"))
            if status:
                stmt = stmt.where(LessonRow.status == status)
            return [
                {
                    "id": r.id,
                    "scope": r.scope,
                    "rule": r.rule,
                    "evidence": json.loads(r.evidence),
                    "status": r.status,
                    "promoted_by": r.promoted_by,
                    "created_at": r.created_at,
                }
                for r in s.scalars(stmt.order_by(LessonRow.created_at))
            ]

    # ---- fit reports -------------------------------------------------------------------------------------------------
    def add_fit_report(self, slug: str, kind: str, result: str, data: dict[str, Any]) -> str:
        fid = "f_" + secrets.token_hex(5)
        with self._lock, self.session() as s:
            s.add(
                FitReportRow(id=fid, slug=slug, kind=kind, result=result, data=json.dumps(data), created_at=time.time())
            )
        return fid

    def fit_reports(self, slug: str) -> list[dict[str, Any]]:
        with self.session() as s:
            rows = s.scalars(
                select(FitReportRow).where(FitReportRow.slug == slug).order_by(FitReportRow.created_at.desc())
            )
            return [
                {"id": r.id, "kind": r.kind, "result": r.result, "data": json.loads(r.data), "created_at": r.created_at}
                for r in rows
            ]


def _score(p: PartRecord, tokens: list[str], numbers: list[float]) -> float:
    text = " ".join([p.title, p.family.value, " ".join(p.tags), p.summary]).lower()
    score = sum(3.0 if t in p.title.lower() else 1.0 for t in tokens if t in text)
    if p.verification and p.verification.verified:
        score += 0.5
    for n in numbers:  # closest default dimension to each number in the query
        dims = [v for v in p.defaults.values() if v > 0]
        if dims:
            rel = min(abs(d - n) / max(n, 1e-6) for d in dims)
            score += max(0.0, 2.0 - 10.0 * rel)
    return score


_registry: Registry | None = None


def get_registry() -> Registry:
    global _registry
    if _registry is None:
        _registry = Registry()
    return _registry
