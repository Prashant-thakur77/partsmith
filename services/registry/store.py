"""Registry storage: parts, needs, lessons, fit reports and coupon fit reports. SQLite under $PARTSMITH_HOME by default, Postgres via DATABASE_URL.

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


class CouponReportRow(Base):
    """One mating feature's tight / ok / loose on a printed fit-test coupon (services/registry/fit_learning.py).
    `device` is a sha256 prefix of the browser's random device id: no accounts, no raw ids stored."""

    __tablename__ = "coupon_reports"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    report_id: Mapped[str] = mapped_column(String(32), index=True)  # one coupon submission (several features)
    preset: Mapped[str] = mapped_column(String(32), index=True)
    device: Mapped[str] = mapped_column(String(32), index=True)
    feature: Mapped[str] = mapped_column(String(64))
    fit: Mapped[str] = mapped_column(String(8))  # tight | ok | loose
    amount: Mapped[str] = mapped_column(String(8), default="")  # barely | very | ""
    base_mm: Mapped[float] = mapped_column(Float)  # clearance in effect when reported
    proposal_mm: Mapped[float] = mapped_column(Float)  # what this report asks for (clamped)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    slug: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[float] = mapped_column(Float, index=True)


class ThumbRow(Base):
    __tablename__ = "thumbnails"
    slug: Mapped[str] = mapped_column(String(120), primary_key=True)
    code_sha: Mapped[str] = mapped_column(String(64))
    params_sha: Mapped[str] = mapped_column(String(64))
    key_1x: Mapped[str] = mapped_column(String(80))
    key_2x: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[float] = mapped_column(Float)


class NeedMetaRow(Base):
    """Extras of a request ("need"): an optional photo and who asked (hashed client fingerprint, never an IP)."""

    __tablename__ = "need_meta"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    photo_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    updated_at: Mapped[float] = mapped_column(Float)


class NeedVoteRow(Base):
    __tablename__ = "need_votes"
    need_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    voter: Mapped[str] = mapped_column(String(32), primary_key=True)  # hashed client fingerprint
    created_at: Mapped[float] = mapped_column(Float)


class UsageRow(Base):
    """API/MCP call counts per day, route and hashed client fingerprint (no raw IPs or user agents)."""

    __tablename__ = "usage"
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    route: Mapped[str] = mapped_column(String(160), primary_key=True)
    client: Mapped[str] = mapped_column(String(32), primary_key=True)
    n: Mapped[int] = mapped_column(Integer, default=0)


class WithdrawnRow(Base):
    """A part an admin took out of search (admin console moderation). The record stays reachable by slug."""

    __tablename__ = "withdrawn"
    slug: Mapped[str] = mapped_column(String(120), primary_key=True)
    reason: Mapped[str] = mapped_column(Text)
    by: Mapped[str] = mapped_column(String(64))
    at: Mapped[float] = mapped_column(Float)


ROLE_REFERENCE_TAG = "role:reference"  # reference objects (ID-1 card, LEGO brick ...): bench-only, hidden from /parts


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
            thumb = s.get(ThumbRow, slug)
            if thumb:
                s.delete(thumb)

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
        role: str | None = None,
        include_withdrawn: bool | None = None,
    ) -> tuple[list[PartRecord], int]:
        """Token search over title/family/tags/summary with numeric boosting ("cooler wheel 32 mm" prefers Ø≈32 parts).
        `role`: None = everything, "part" = functional parts only, "reference" = reference objects only.
        Withdrawn parts are left out of public searches (any `role`) unless `include_withdrawn`; the default
        `role=None` (internal callers: dedupe, lineage, passport ids) still sees them."""
        parts, total, _, _ = self.search_scored(
            q, family=family, verified=verified, origin=origin, sort=sort, cursor=cursor, limit=limit, role=role,
            include_withdrawn=include_withdrawn,
        )  # fmt: skip
        return parts, total

    def search_scored(
        self,
        q: str = "",
        *,
        family: str | None = None,
        verified: bool | None = None,
        origin: str | None = None,
        sort: str = "relevance",
        cursor: int = 0,
        limit: int = 24,
        role: str | None = None,
        include_withdrawn: bool | None = None,
    ) -> tuple[list[PartRecord], int, list[float], float | None]:
        """`search` plus coverage: (page, total, coverage of each part on the page, best coverage over every candidate).
        Coverage is None (and the list empty) when the query has no words or numbers to match."""
        tokens, numbers = query_terms(q)
        with self.session() as s:
            stmt = select(PartRow)
            if family:
                stmt = stmt.where(PartRow.family == family)
            if verified is not None:
                stmt = stmt.where(PartRow.verified == verified)
            if origin:
                stmt = stmt.where(PartRow.origin == origin)
            if role == "reference":
                stmt = stmt.where(PartRow.search_text.contains(ROLE_REFERENCE_TAG))
            elif role == "part":
                stmt = stmt.where(~PartRow.search_text.contains(ROLE_REFERENCE_TAG))
            if not (role is None if include_withdrawn is None else include_withdrawn):
                stmt = stmt.where(PartRow.slug.not_in(select(WithdrawnRow.slug)))
            if tokens:
                stmt = stmt.where(or_(*[PartRow.search_text.contains(_stem(t)) for t in tokens]))
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
        page = parts[cursor : cursor + limit]
        if not tokens and not numbers:
            return page, len(parts), [], None
        best = max((coverage(p, tokens, numbers) for p in parts), default=0.0)
        return page, len(parts), [coverage(p, tokens, numbers) for p in page], best

    def families(self, *, include_reference: bool = True) -> list[dict[str, Any]]:
        with self.session() as s:
            stmt = select(PartRow.family, func.count(), func.sum(func.cast(PartRow.verified, Integer)))
            if not include_reference:
                stmt = stmt.where(~PartRow.search_text.contains(ROLE_REFERENCE_TAG))
            rows = s.execute(stmt.group_by(PartRow.family)).all()
        return [{"family": f, "count": int(c), "verified": int(v or 0)} for f, c, v in rows]

    def stats(self) -> dict[str, Any]:
        with self.session() as s:
            total = s.scalar(select(func.count()).select_from(PartRow)) or 0
            verified = s.scalar(select(func.count()).select_from(PartRow).where(PartRow.verified.is_(True))) or 0
            by_origin = dict(s.execute(select(PartRow.origin, func.count()).group_by(PartRow.origin)).all())
            records = list(s.scalars(select(PartRow.record)))
            reference = (
                s.scalar(
                    select(func.count()).select_from(PartRow).where(PartRow.search_text.contains(ROLE_REFERENCE_TAG))
                )
                or 0
            )
        grams = sum((json.loads(r).get("facts") or {}).get("mass_g_pla", 0.0) for r in records)
        return {
            "parts": int(total),
            "verified": int(verified),
            "synthetic": int(by_origin.get("synthetic", 0)),
            "real": int(by_origin.get("real", 0)),
            "reference_object": int(by_origin.get("reference_object", 0)),
            "grams_pla": round(float(grams), 1),
            "reference": int(reference),
        }

    # ---- thumbnails ------------------------------------------------------------------------------------------------
    # ---- moderation (admin console) ----------------------------------------------------------------------------------
    def withdraw(self, slug: str, reason: str, by: str) -> dict[str, Any]:
        """Take a part out of search; it stays reachable by slug. KeyError for an unknown slug."""
        with self._lock, self.session() as s:
            if s.get(PartRow, slug) is None:
                raise KeyError(slug)
            row = WithdrawnRow(slug=slug, reason=reason, by=by, at=time.time())
            s.merge(row)
            return {"reason": row.reason, "by": row.by, "at": row.at}

    def restore(self, slug: str) -> bool:
        """Put a withdrawn part back in search. Returns whether it was withdrawn."""
        with self._lock, self.session() as s:
            row = s.get(WithdrawnRow, slug)
            if row is None:
                return False
            s.delete(row)
            return True

    def withdrawal(self, slug: str) -> dict[str, Any] | None:
        with self.session() as s:
            r = s.get(WithdrawnRow, slug)
            return {"reason": r.reason, "by": r.by, "at": r.at} if r else None

    def withdrawn(self) -> dict[str, dict[str, Any]]:
        with self.session() as s:
            return {r.slug: {"reason": r.reason, "by": r.by, "at": r.at} for r in s.scalars(select(WithdrawnRow))}

    def set_thumbnail(self, slug: str, *, code_sha: str, params_sha: str, key_1x: str, key_2x: str) -> None:
        """Remember the blob keys of a part's rendered thumbnail (1x and 2x) and what they were rendered from."""
        row = ThumbRow(
            slug=slug, code_sha=code_sha, params_sha=params_sha, key_1x=key_1x, key_2x=key_2x, created_at=time.time()
        )
        with self._lock, self.session() as s:
            s.merge(row)

    def thumbnail(self, slug: str) -> dict[str, Any] | None:
        with self.session() as s:
            row = s.get(ThumbRow, slug)
            if row is None:
                return None
            return {"code_sha": row.code_sha, "params_sha": row.params_sha, "key_1x": row.key_1x, "key_2x": row.key_2x}

    def thumbnails(self) -> dict[str, dict[str, Any]]:
        with self.session() as s:
            return {
                r.slug: {"code_sha": r.code_sha, "params_sha": r.params_sha, "key_1x": r.key_1x, "key_2x": r.key_2x}
                for r in s.scalars(select(ThumbRow))
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

    def request_need(self, query: str, voter: str) -> tuple[Need, bool]:
        """Create a request, or vote for the same request (case-insensitive) once per voter. Returns (need, counted)."""
        query = query.strip()[:300]
        with self._lock, self.session() as s:
            row = s.scalars(select(NeedRow).where(func.lower(NeedRow.query) == query.lower())).first()
            counted = True
            if row is None:
                row = NeedRow(
                    id="n_" + secrets.token_hex(5), query=query, votes=1, status="open", created_at=time.time()
                )
                s.add(row)
                s.add(NeedVoteRow(need_id=row.id, voter=voter, created_at=time.time()))
            elif s.get(NeedVoteRow, (row.id, voter)) is None:
                s.add(NeedVoteRow(need_id=row.id, voter=voter, created_at=time.time()))
                row.votes += 1
            else:
                counted = False
            return Need(
                id=row.id, query=row.query, votes=row.votes, status=row.status, created_at=row.created_at
            ), counted

    def get_need(self, nid: str) -> Need | None:
        with self.session() as s:
            r = s.get(NeedRow, nid)
            return Need(id=r.id, query=r.query, votes=r.votes, status=r.status, created_at=r.created_at) if r else None

    def vote_need(self, nid: str, voter: str) -> tuple[Need, bool]:
        """One vote per voter (hashed fingerprint). Returns (need, counted). KeyError for unknown ids."""
        with self._lock, self.session() as s:
            r = s.get(NeedRow, nid)
            if r is None:
                raise KeyError(nid)
            counted = s.get(NeedVoteRow, (nid, voter)) is None
            if counted:
                s.add(NeedVoteRow(need_id=nid, voter=voter, created_at=time.time()))
                r.votes += 1
            return Need(id=r.id, query=r.query, votes=r.votes, status=r.status, created_at=r.created_at), counted

    def set_need_status(self, nid: str, status: str) -> Need:
        with self._lock, self.session() as s:
            r = s.get(NeedRow, nid)
            if r is None:
                raise KeyError(nid)
            r.status = status
            return Need(id=r.id, query=r.query, votes=r.votes, status=r.status, created_at=r.created_at)

    def set_need_photo(self, nid: str, photo_key: str) -> None:
        with self._lock, self.session() as s:
            s.merge(NeedMetaRow(id=nid, photo_key=photo_key, updated_at=time.time()))

    def need_photos(self) -> dict[str, str]:
        with self.session() as s:
            return {r.id: r.photo_key for r in s.scalars(select(NeedMetaRow)) if r.photo_key}

    def needs(self, limit: int = 50) -> list[Need]:
        with self.session() as s:
            rows = s.scalars(select(NeedRow).order_by(NeedRow.votes.desc(), NeedRow.created_at.desc()).limit(limit))
            return [Need(id=r.id, query=r.query, votes=r.votes, status=r.status, created_at=r.created_at) for r in rows]

    # ---- usage -------------------------------------------------------------------------------------------------------
    def add_usage(self, counts: dict[tuple[str, str, str], int]) -> None:
        """Add (day, route, client) → n counts."""
        if not counts:
            return
        with self._lock, self.session() as s:
            for (day, route, client), n in counts.items():
                row = s.get(UsageRow, (day, route, client))
                if row is None:
                    s.add(UsageRow(day=day, route=route, client=client, n=n))
                else:
                    row.n += n

    def usage(self, since_day: str | None = None) -> list[tuple[str, str, str, int]]:
        with self.session() as s:
            stmt = select(UsageRow)
            if since_day:
                stmt = stmt.where(UsageRow.day >= since_day)
            return [(r.day, r.route, r.client, r.n) for r in s.scalars(stmt)]

    def lesson(self, lid: str) -> dict[str, Any] | None:
        return next((x for x in self.lessons() if x["id"] == lid), None)

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

    # ---- coupon fit reports ------------------------------------------------------------------------------------------
    def add_coupon_reports(self, rows: list[dict[str, Any]]) -> None:
        """Insert one coupon submission's feature rows (keys = CouponReportRow columns except id/created_at)."""
        now = time.time()
        with self._lock, self.session() as s:
            for i, r in enumerate(rows):
                s.add(CouponReportRow(id="c_" + secrets.token_hex(6), created_at=now + i * 1e-6, **r))

    def coupon_reports(self, preset: str, device: str, limit: int = 200) -> list[dict[str, Any]]:
        """Newest first."""
        with self.session() as s:
            rows = s.scalars(
                select(CouponReportRow)
                .where(CouponReportRow.preset == preset, CouponReportRow.device == device)
                .order_by(CouponReportRow.created_at.desc())
                .limit(limit)
            )
            return [
                {
                    "id": r.id,
                    "report_id": r.report_id,
                    "feature": r.feature,
                    "fit": r.fit,
                    "amount": r.amount,
                    "base_mm": r.base_mm,
                    "proposal_mm": r.proposal_mm,
                    "job_id": r.job_id,
                    "slug": r.slug,
                    "created_at": r.created_at,
                }
                for r in rows
            ]


QUERY_STOPWORDS = frozenset(
    {"mm", "for", "the", "and", "with", "my", "of", "to", "in", "on", "an", "part", "parts", "replacement", "new",
     "broken", "need", "spare"}
)  # fmt: skip
MATCH_GOOD = 0.75  # share of the query's words and numbers a part must match to be a good match
MATCH_PARTIAL = 0.5  # below this nothing really matches (the search goes on the missed-search list)
NUMBER_TOL_REL = 0.1  # a number in the query matches a part dimension within 10 % ...
NUMBER_TOL_MM = 0.5  # ... or within half a millimetre, whichever is larger


def query_terms(q: str) -> tuple[list[str], list[float]]:
    """Words (two letters or more, filler words dropped) and numbers of a search query."""
    tokens = [t for t in re.findall(r"[a-z]+", q.lower()) if len(t) > 1 and t not in QUERY_STOPWORDS]
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", q)]
    return tokens, numbers


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def _word_hit(token: str, words: set[str]) -> bool:
    t = _stem(token)
    return any(w == t or w.startswith(t) or _stem(w) == t for w in words)


def number_hit(n: float, dims: list[float]) -> bool:
    """A query number matches a part dimension within max(10 %, 0.5 mm)."""
    tol = max(NUMBER_TOL_MM, NUMBER_TOL_REL * abs(n))
    return any(abs(d - n) <= tol for d in dims)


def coverage(p: PartRecord, tokens: list[str], numbers: list[float]) -> float:
    """Share (0..1) of the query's words and numbers this part matches: a word must start a word of the part's title,
    family, tags, summary or slug (plural "s" ignored); a number must lie within max(10 %, 0.5 mm) of one of the part's
    default dimensions or a number written in its title or tags. 0.0 for an empty query."""
    terms = len(tokens) + len(numbers)
    if not terms:
        return 0.0
    text = " ".join([p.title, p.family.value.replace("_", " "), " ".join(p.tags), p.summary, p.slug.replace("-", " ")])
    words = set(re.findall(r"[a-z]+", text.lower()))
    dims = [float(v) for v in p.defaults.values() if v > 0]
    dims += [float(n) for n in re.findall(r"\d+(?:\.\d+)?", " ".join([p.title, " ".join(p.tags)]))]
    hits = sum(1 for t in tokens if _word_hit(t, words)) + sum(1 for n in numbers if number_hit(n, dims))
    return round(hits / terms, 3)


def match_label(best: float | None) -> str:
    """'all' (no query), 'good', 'partial' or 'none' from the best coverage of a search."""
    if best is None:
        return "all"
    if best >= MATCH_GOOD:
        return "good"
    return "partial" if best >= MATCH_PARTIAL else "none"


def match_hint(match: str) -> str | None:
    """Plain words for an agent or a person when the registry has no close match."""
    if match == "none":
        return "No close match — describe it at /describe or fix from a photo at /fix (or request it at /requests)."
    if match == "partial":
        return (
            "Only a partial match — the closest parts miss some of your words or sizes. Check the sizes, or describe "
            "it at /describe or fix from a photo at /fix."
        )
    return None


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
