"""The one way parts enter the registry: `publish_part` dedupes before it writes.

Identity of a part = its program with every PARAMS default normalised (so the same template at different defaults is the
same program) + its clamped parameter values. Publishing a part whose identity already exists returns that part (and
updates it, bumping `version`, only when something meaningful changed: verification, status, facts, title ...). A new
identity whose slug is taken gets a descriptive suffix from the knobs that differ ("cable-clip-40mm-3ch"); when it is
the same program at other values it records `forked_from` = the existing slug, which the colliding part shows as a
`variant_of` lineage entry.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from partsmith_schemas import PartRecord
from partsmith_schemas.verification import ParamSpec

from services.geom_worker.program import ProgramError, clamp, code_sha, parse_params, set_defaults
from services.registry.store import Registry, get_registry

Action = Literal["created", "updated", "unchanged", "renamed"]
MAIN_DIMS = ("length", "diameter", "outer_d")
_ABBR = {"channel": "ch", "knuckle": "kn", "spoke": "sp", "gusset": "gus", "groove": "gr", "tongue": "tg"}
_COMPARED = ("title", "summary", "tags", "status", "verification", "facts", "mating", "licence")


@dataclass
class PublishOutcome:
    part: PartRecord  # the record now in the registry
    action: Action
    requested_slug: str
    duplicate_of: str | None = None  # set when an identical part already existed under another slug

    def to_dict(self) -> dict[str, object]:
        return {"slug": self.part.slug, "action": self.action, "requested_slug": self.requested_slug,
                "duplicate_of": self.duplicate_of, "version": self.part.version}  # fmt: skip


def program_identity(code: str) -> str:
    """sha256 of the program with every PARAMS default set to its minimum (defaults are values, not the program)."""
    try:
        specs = parse_params(code)
        return code_sha(set_defaults(code, {s.name: s.min for s in specs}))
    except (ProgramError, SyntaxError):
        return code_sha(code)


def values_of(part: PartRecord) -> dict[str, float]:
    try:
        values, _ = clamp(part.defaults, list(part.params))
    except (KeyError, ProgramError):
        values = dict(part.defaults)
    return {k: round(float(v), 6) for k, v in sorted(values.items())}


def identity(part: PartRecord) -> str:
    blob = json.dumps([program_identity(part.code), values_of(part)], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _num(v: float) -> str:
    return f"{v:g}".replace(".", "p").replace("-", "m")


def _token(spec: ParamSpec, v: float) -> str:
    if spec.topology:
        word = spec.name.replace("_count", "").split("_")[0]
        return f"{round(v)}{_ABBR.get(word, word[:4])}"
    if spec.name in MAIN_DIMS:
        return f"{_num(v)}mm"
    return f"{spec.name.split('_')[0][:5]}{_num(v)}{spec.unit}"


def variant_suffix(new: PartRecord, old: PartRecord) -> str:
    """Slug suffix from the knobs where `new` differs from `old` (main size and topology first, at most two)."""
    a, b = values_of(new), values_of(old)
    specs = {p.name: p for p in new.params}
    diff = [n for n in a if n in b and abs(a[n] - b[n]) > 1e-9 and n in specs]

    def rank(n: str) -> tuple[int, float]:
        s = specs[n]
        first = 0 if n in MAIN_DIMS else 1 if s.topology else 2
        return first, -abs(a[n] - b[n]) / max(abs(b[n]), 1e-6)

    tokens = [_token(specs[n], a[n]) for n in sorted(diff, key=rank)[:2]]
    if not tokens:  # a different program under the same slug: describe it by its main size
        main = next((n for n in MAIN_DIMS if n in a), None)
        tokens = [_token(specs[main], a[main])] if main else []
    return "-".join(tokens)


def _changed(new: PartRecord, old: PartRecord) -> bool:
    n, o = new.model_dump(mode="json", include=set(_COMPARED)), old.model_dump(mode="json", include=set(_COMPARED))
    if n.get("verification") and o.get("verification"):  # the run time of a re-run is not a change
        for v in (n["verification"], o["verification"]):
            v.pop("ms", None)
    return bool(n != o)


def _merge(new: PartRecord, old: PartRecord) -> PartRecord:
    prov = new.provenance.model_copy(update={"forked_from": old.provenance.forked_from or new.provenance.forked_from})
    return new.model_copy(update={"id": old.id, "slug": old.slug, "version": old.version + 1,
                                  "created_at": old.created_at, "provenance": prov})  # fmt: skip


def find_duplicate(part: PartRecord, reg: Registry | None = None, *, exclude: str | None = None) -> PartRecord | None:
    """An existing part with the same identity (same slug preferred)."""
    reg = reg or get_registry()
    want = identity(part)
    same = reg.get_part(part.slug)
    if same is not None and same.slug != exclude and identity(same) == want:
        return same
    every, _ = reg.search("", limit=100_000, sort="newest")
    for other in sorted(every, key=lambda p: p.created_at):  # the oldest copy is the canonical one
        if other.slug != exclude and other.slug != part.slug and identity(other) == want:
            return other
    return None


def publish_part(part: PartRecord, *, reg: Registry | None = None, render: bool = True) -> PublishOutcome:
    """Publish with dedupe. Returns the record now in the registry and what happened:
    `unchanged` (identical part exists), `updated` (same identity, new facts/verification → version + 1),
    `renamed` (slug taken by a different part → descriptive suffix), `created`.
    `render` fills printing facts and thumbnails (see parts.after_publish)."""
    reg = reg or get_registry()
    requested = part.slug
    dup = find_duplicate(part, reg)
    if dup is not None:
        if _changed(part, dup):
            merged = _merge(part, dup)
            reg.upsert_part(merged)
            outcome = PublishOutcome(merged, "updated", requested, dup.slug if dup.slug != requested else None)
        else:
            outcome = PublishOutcome(dup, "unchanged", requested, dup.slug if dup.slug != requested else None)
    else:
        taken = reg.get_part(part.slug)
        if taken is not None:
            same_program = program_identity(taken.code) == program_identity(part.code)
            suffix = variant_suffix(part, taken) or "v2"
            base = f"{part.slug}-{suffix}"[:80].strip("-")
            slug, n = base, 2
            while reg.get_part(slug) is not None:
                slug, n = f"{base}-{n}", n + 1
            prov = part.provenance
            if same_program and not prov.forked_from:
                prov = prov.model_copy(update={"forked_from": taken.slug})
            part = part.model_copy(update={"slug": slug, "provenance": prov})
            reg.upsert_part(part)
            outcome = PublishOutcome(part, "renamed", requested)
        else:
            reg.upsert_part(part)
            outcome = PublishOutcome(part, "created", requested)
    if render:
        from services.registry.parts import after_publish

        outcome.part = after_publish(outcome.part, reg=reg)
    return outcome


def dedupe_published(slug: str, *, reg: Registry | None = None, render: bool = True) -> PublishOutcome:
    """For a record someone already upserted under `slug` (e.g. a publish path that bypassed `publish_part`): if an
    older identical part exists, fold this one into it (delete `slug`, update the older one when something changed)."""
    reg = reg or get_registry()
    part = reg.get_part(slug)
    if part is None:
        raise KeyError(slug)
    dup = find_duplicate(part, reg, exclude=slug)
    if dup is None or dup.created_at > part.created_at:
        outcome = PublishOutcome(part, "created", slug)
    else:
        reg.delete_part(slug)
        if _changed(part, dup):
            merged = _merge(part, dup)
            reg.upsert_part(merged)
            outcome = PublishOutcome(merged, "updated", slug, dup.slug)
        else:
            outcome = PublishOutcome(dup, "unchanged", slug, dup.slug)
    if render:
        from services.registry.parts import after_publish

        outcome.part = after_publish(outcome.part, reg=reg)
    return outcome
