"""Repair passport: a short, stable, human-readable id that brings a printed part back without new photos.

Id = the first 6 symbols (30 bits) of a sha256 in Crockford base32 (no I, L, O, U; read case-insensitively, with O
read as 0 and I/L as 1), so it stays short enough to deboss on a part at 4 mm cap height:

- a published part: sha256("partsmith-passport/part/<identity>/<version>"), where identity is the publish dedupe
  identity (program with PARAMS defaults normalised + clamped values). Same part → same id; a new version → a new id.
  Versions only change when facts/verification change for the same identity, so an older version's id still resolves
  to the same geometry (`superseded: true`).
- a job: sha256("partsmith-passport/job/<job id>"). Once the job is published it resolves to its part.

No personal data goes in. 30 bits make a collision unlikely for a registry of thousands of parts (about 1 in 2000 for
1000 ids); resolution is deterministic (current part versions, then older versions, then jobs) and `ambiguous` lists
any other match.
"""

from __future__ import annotations

import difflib
import hashlib
import os
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from partsmith_schemas import PartRecord, Passport, PassportLink, PassportPreset, PassportShip
from partsmith_schemas.partspec import Family

from services.registry import gate, presets
from services.registry.publish import identity, values_of
from services.registry.store import Registry, get_registry

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ID_LEN = 6
API = "/api/v1"
_READ_AS = {"O": "0", "I": "1", "L": "1"}
_IDENTITY: dict[tuple[str, str, int], str] = {}
_LOCK = threading.Lock()


def encode(digest: bytes, n: int = ID_LEN) -> str:
    """The first `n` base32 symbols of a digest (5 bits each, most significant first)."""
    bits = int.from_bytes(digest[:8], "big")
    return "".join(ALPHABET[(bits >> (64 - 5 * (i + 1))) & 31] for i in range(n))


def normalize(raw: str) -> str | None:
    """Canonical form of a typed or scanned id ("7kq-3mz" → "7KQ3MZ"), or None when it cannot be an id."""
    s = "".join(ch for ch in raw.strip().upper() if ch not in "- _")
    s = "".join(_READ_AS.get(ch, ch) for ch in s)
    return s if len(s) == ID_LEN and all(ch in ALPHABET for ch in s) else None


def _identity(part: PartRecord) -> str:
    key = (part.slug, part.code_sha, part.version)
    with _LOCK:
        hit = _IDENTITY.get(key)
    if hit is None:
        hit = identity(part)
        with _LOCK:
            _IDENTITY[key] = hit
    return hit


def part_id(part: PartRecord, version: int | None = None) -> str:
    v = part.version if version is None else int(version)
    return encode(hashlib.sha256(f"partsmith-passport/part/{_identity(part)}/{v}".encode()).digest())


def job_id(job: str) -> str:
    return encode(hashlib.sha256(f"partsmith-passport/job/{job}".encode()).digest())


def web_base() -> str:
    """Absolute origin of the web app for printed links (the repair card): PARTSMITH_PUBLIC_URL, else the dev
    server. Requests use their own origin instead (`services.api.common.public_base`)."""
    return (os.environ.get("PARTSMITH_PUBLIC_URL", "").strip() or "http://localhost:3000").rstrip("/")


def link(pid: str) -> PassportLink:
    return PassportLink(id=pid, url=f"/p/{pid}", qr_svg_url=f"{API}/passport/{pid}/qr.svg",
                        qr_png_url=f"{API}/passport/{pid}/qr.png")  # fmt: skip


@dataclass
class Match:
    kind: str  # "part" | "job"
    part: PartRecord | None = None
    version: int | None = None  # the part version the id was issued for
    job: str | None = None
    others: list[str] = field(default_factory=list)  # other records with the same id (a collision)


def _parts(reg: Registry) -> list[PartRecord]:
    every, _ = reg.search("", limit=1_000_000, sort="newest")
    return sorted(every, key=lambda p: (p.created_at, p.slug))


def find(pid: str, reg: Registry | None = None, job_ids: Iterable[str] = ()) -> Match | None:
    """The record a (normalized) passport id stands for, or None."""
    reg = reg or get_registry()
    hits: list[Match] = []
    parts = _parts(reg)
    for p in parts:
        if part_id(p) == pid:
            hits.append(Match("part", part=p, version=p.version))
    for p in parts:
        for v in range(p.version - 1, 0, -1):
            if part_id(p, v) == pid:
                hits.append(Match("part", part=p, version=v))
    for j in sorted(set(job_ids)):
        if job_id(j) == pid:
            hits.append(Match("job", job=j))
    if not hits:
        return None
    first = hits[0]
    first.others = [m.part.slug if m.part else f"job:{m.job}" for m in hits[1:]]
    return first


def known_ids(reg: Registry | None = None, job_ids: Iterable[str] = ()) -> list[str]:
    reg = reg or get_registry()
    return [part_id(p) for p in _parts(reg)] + [job_id(j) for j in job_ids]


def closest(raw: str, reg: Registry | None = None, job_ids: Iterable[str] = (), n: int = 3) -> list[str]:
    want = normalize(raw) or raw.strip().upper()
    return difflib.get_close_matches(want, known_ids(reg, job_ids), n=n, cutoff=0.5)


def preset_of(spec: dict[str, Any] | None) -> PassportPreset:
    """The fit preset the reprint starts from: the job's stated material + printer, else the PLA 0.4 mm default."""
    fit = (spec or {}).get("fit") or {}
    pid = presets.for_fit(fit.get("material"), fit.get("printer")) if fit else None
    source = "job_spec" if pid else "default"
    p = presets.BY_ID[pid or presets.DEFAULT_ID]
    return PassportPreset(id=p.id, title=p.title, source=source, delta_mm=p.delta_mm)


def fix_url(title: str, family: str, pid: str) -> str:
    from urllib.parse import urlencode

    intent = f"Replacement for {title} (passport {pid}): it broke in a new place."
    return "/fix?" + urlencode({"family": family, "intent": intent})


def _ship(decision: gate.ShipDecision) -> PassportShip:
    return PassportShip(status=decision.status, reason=decision.reason, needs_ack=decision.needs_ack,
                        source=decision.source)  # fmt: skip


def for_part(part: PartRecord, *, pid: str, version: int | None = None, spec: dict[str, Any] | None = None,
             job: str | None = None, job_status: str | None = None) -> Passport:  # fmt: skip
    """The passport of a published part (`version` = the version the id was issued for)."""
    v = part.verification
    issued = part.version if version is None else version
    notes: list[str] = []
    if issued != part.version:
        notes.append(f"issued for version {issued}; version {part.version} has the same program and values "
                     "(only its record changed), so the reprint is the same geometry")  # fmt: skip
    if job is not None:
        notes.append(f"this passport was printed for job {job}, which was published as {part.slug}")
    status = v.status if v is not None else "unknown"
    return Passport(
        id=pid, kind="part", url=f"/p/{pid}", title=part.title, family=part.family, slug=part.slug, version=issued,
        current_version=part.version, superseded=issued != part.version, job_id=job or part.provenance.job_id,
        job_status=job_status, published=True, values=values_of(part), preset=preset_of(spec), status=status,
        verified=bool(v and v.verified), max_error_mm=v.max_error_mm if v else None,
        threshold_mm=v.thresholds.hausdorff_mm if v else None, ship=_ship(gate.decide_part(part)),
        origin=part.provenance.origin, page_url=f"/parts/{part.slug}", bake_url=f"{API}/parts/{part.slug}/bake",
        presets_url=f"{API}/parts/{part.slug}/presets", qr_svg_url=link(pid).qr_svg_url,
        qr_png_url=link(pid).qr_png_url, fix_url=fix_url(part.title, part.family.value, pid), notes=notes,
    )  # fmt: skip


def for_job(*, pid: str, job: str, title: str, family: str, values: dict[str, float], spec: dict[str, Any] | None,
            verification: Any, decision: gate.ShipDecision, origin: Any, job_status: str) -> Passport:  # fmt: skip
    """The passport of a job that was never published (resolves to its job page)."""
    v = verification
    fam = Family(family) if family in Family._value2member_map_ else Family("custom")
    return Passport(
        id=pid, kind="job", url=f"/p/{pid}", title=title or "Replacement part", family=fam, job_id=job,
        job_status=job_status, published=False, values={k: round(float(x), 6) for k, x in sorted(values.items())},
        preset=preset_of(spec), status=v.status if v is not None else "unknown", verified=bool(v and v.verified),
        max_error_mm=v.max_error_mm if v else None, threshold_mm=v.thresholds.hausdorff_mm if v else None,
        ship=_ship(decision), origin=origin, page_url=f"/jobs/{job}", bake_url=f"{API}/jobs/{job}/bake",
        presets_url=f"{API}/jobs/{job}/presets", qr_svg_url=link(pid).qr_svg_url, qr_png_url=link(pid).qr_png_url,
        fix_url=fix_url(title or "this part", fam.value, pid),
        notes=["not published: the passport points at the job on this server (its current part program and values)"],
    )  # fmt: skip
