"""Save a variant: a registry part re-baked at new knob values becomes its own registry part, with honest provenance.

The variant is the parent's program with the PARAMS defaults set to the new (clamped) values. It is baked in the
sandbox first (a program that does not build is refused). Its verification record never copies the parent's photo
comparison: it is `best_effort` with the plain-words reason "a variant of a verified part, not itself checked against
a photo", and every knob that changed is listed in `unchecked` with its old and new value. So the export gate asks for
an acknowledgement until someone re-verifies the variant with a photo (/fix). Publishing goes through `publish_part`
(dedupe, descriptive slug suffix, `forked_from` = the parent), and the route is admin-only like every publish.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Mapping
from typing import Any

from partsmith_schemas import PartRecord, Verification
from partsmith_schemas.registry import Provenance
from partsmith_schemas.verification import UncheckedValue

from services.geom_worker.program import clamp, code_sha, parse_params, set_defaults
from services.registry import parts as P
from services.registry.publish import PublishOutcome, publish_part
from services.registry.store import Registry, get_registry


class NoChange(ValueError):
    """The requested values equal the parent's: there is nothing to save."""


def variant_reason(parent: PartRecord) -> str:
    v = parent.verification
    what = "a verified part" if v is not None and v.verified else "a best-effort part"
    return (
        f"A variant of {what} ({parent.slug} v{parent.version}) at new knob values; not itself checked against a "
        "photo. Re-verify it with a photo on /fix before relying on the changed sizes."
    )


def changed_knobs(parent: PartRecord, values: Mapping[str, float]) -> dict[str, tuple[float, float]]:
    """knob -> (parent value, new value) for every knob that differs (after clamping)."""
    base, _ = clamp(parent.defaults, list(parent.params))
    new, _ = clamp(dict(values), list(parent.params))
    return {k: (float(base[k]), float(new[k])) for k in new if abs(float(new[k]) - float(base[k])) > 1e-9}


def build_variant(parent: PartRecord, values: Mapping[str, float], *, title: str | None = None) -> PartRecord:
    """The variant record (not published). Raises NoChange, UnknownParamError or BakeError (it must build)."""
    full = {**parent.defaults, **{k: float(v) for k, v in values.items()}}
    diff = changed_knobs(parent, full)
    if not diff:
        raise NoChange("these are the part's own values: change a knob first")
    clamped, _ = clamp(full, list(parent.params))
    out = P.bake_output(parent, clamped, ("stl",))  # must build in the sandbox; also gives the facts
    code = set_defaults(parent.code, clamped)
    specs = parse_params(code)
    by_name = {p.name: p for p in specs}
    reason = variant_reason(parent)
    unchecked = [
        UncheckedValue(
            param=k,
            label=by_name[k].label,
            value=new,
            unit=by_name[k].unit if by_name[k].unit in ("mm", "deg", "") else "",
            note=f"changed from {old:g} in the {'verified' if parent.status == 'verified' else 'parent'} part; "
            "not checked against a photo",
        )
        for k, (old, new) in diff.items()
    ]
    origin = parent.verification.origin if parent.verification is not None else parent.provenance.origin
    ver = Verification(verified=False, status="best_effort", reasons=[reason], unchecked=unchecked, origin=origin)
    changes = ", ".join(f"{k} {old:g} → {new:g}" for k, (old, new) in diff.items())
    return PartRecord(
        id="p_" + secrets.token_hex(6),
        slug=parent.slug,  # publish_part renames it with a suffix from the knobs that differ
        title=(title or "").strip()[:120] or parent.title,
        family=parent.family,
        summary=parent.summary,
        tags=[t for t in parent.tags if t != "variant"] + ["variant"],
        status="best_effort",
        params=specs,
        defaults={s.name: float(s.default) for s in specs},
        code=code,
        code_sha=code_sha(code),
        verification=ver,
        provenance=Provenance(
            origin=parent.provenance.origin,
            job_id=parent.provenance.job_id,
            photo_shas=[],
            builder_model=parent.provenance.builder_model,
            provider_mode=parent.provenance.provider_mode,
            created_by="variant",
            forked_from=parent.slug,
            note=f"Variant of {parent.slug} v{parent.version}: {changes}. {reason}",
        ),
        facts=out.facts,
        licence=parent.licence,
        created_at=time.time(),
    )


def save_variant(
    slug: str, values: Mapping[str, float], *, title: str | None = None, reg: Registry | None = None
) -> tuple[PublishOutcome, dict[str, tuple[float, float]]]:
    """Build and publish (with dedupe) a variant of registry part `slug`. Returns the outcome and the changed knobs."""
    reg = reg or get_registry()
    parent = P.require_part(slug, reg)
    record = build_variant(parent, values, title=title)
    diff = changed_knobs(parent, {**parent.defaults, **dict(values)})
    return publish_part(record, reg=reg), diff


def outcome_json(outcome: PublishOutcome, diff: Mapping[str, tuple[float, float]]) -> dict[str, Any]:
    return {
        **outcome.to_dict(),
        "part": P.part_detail(outcome.part),
        "changed": [{"param": k, "from": a, "to": b} for k, (a, b) in diff.items()],
        "label": outcome.part.verification.reasons[0] if outcome.part.verification else "",
    }


__all__ = ["NoChange", "build_variant", "changed_knobs", "outcome_json", "save_variant", "variant_reason"]
