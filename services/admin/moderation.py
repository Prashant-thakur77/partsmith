"""Registry moderation: every part with its publish criteria evaluated by code, and withdraw / put back.

Criteria are read from the stored record and the review chains, never typed by hand: verified by code, max error
within the record's own limit, accepted by a person (a test review never counts), has knobs, carries a licence.
A withdrawn part leaves search (`/parts`, MCP `search_parts`, llms.txt) but stays reachable by slug, flagged.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from partsmith_schemas import PartRecord

from services.admin import audit
from services.registry.store import ROLE_REFERENCE_TAG, Registry, get_registry
from services.review import store as review_store

SOURCE = "registry records + review chains on this server"


class ModerationError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def person_accepts() -> dict[str, dict[str, Any]]:
    """Accepts by a person, keyed by published slug and by job id: {"job_id", "at", "root_job"}. Tests excluded."""
    out: dict[str, dict[str, Any]] = {}
    for state in review_store._all_states():
        for r in state.get("rounds") or []:
            if r.get("decision") != "accept" or r.get("by", "person") != "person":
                continue
            info = {"job_id": r.get("job_id"), "at": r.get("at"), "root_job": state.get("root_job")}
            out[f"job:{r.get('job_id')}"] = info
            if r.get("part_slug"):
                out[f"slug:{r['part_slug']}"] = info
    return out


def criteria(part: PartRecord, accepts: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """[{"key", "label", "ok": bool | None, "value", "source"}]; ok None = not applicable / unknown."""
    v = part.verification
    limit = v.thresholds.hausdorff_mm if v is not None else None
    err = v.max_error_mm if v is not None else None
    acc = accepts.get(f"slug:{part.slug}") or (
        accepts.get(f"job:{part.provenance.job_id}") if part.provenance.job_id else None
    )
    return [
        {
            "key": "verified",
            "label": "Verified by code",
            "ok": bool(v and v.verified),
            "value": v.status if v is not None else None,
            "source": "verification.verified",
        },
        {
            "key": "max_error",
            "label": "Max error within the limit",
            "ok": (err <= limit) if err is not None and limit is not None else None,
            "value": {"max_error_mm": err, "limit_mm": limit},
            "source": "verification.max_error_mm vs verification.thresholds.hausdorff_mm",
        },
        {
            "key": "accepted_by_person",
            "label": "Accepted by a person",
            "ok": acc is not None,
            "value": dict(acc) if acc else None,
            "source": "review chains (test reviews do not count)",
        },
        {
            "key": "has_params",
            "label": "Has knobs",
            "ok": len(part.params) > 0,
            "value": len(part.params),
            "source": "record.params",
        },
        {
            "key": "licence",
            "label": "Has a licence",
            "ok": bool(part.licence.strip()),
            "value": part.licence or None,
            "source": "record.licence",
        },
    ]


def parts(reg: Registry | None = None) -> dict[str, Any]:
    """Every part (reference objects included, labelled) with its criteria and withdrawal."""
    reg = reg or get_registry()
    every, _ = reg.search("", limit=1_000_000, sort="newest", include_withdrawn=True)
    withdrawn = reg.withdrawn()
    accepts = person_accepts()
    items = []
    for p in every:
        c = criteria(p, accepts)
        items.append(
            {
                "slug": p.slug,
                "title": p.title,
                "family": p.family.value,
                "status": p.status,
                "origin": p.provenance.origin.value,
                "reference": ROLE_REFERENCE_TAG in p.tags,
                "created_at": p.created_at,
                "criteria": c,
                "met": sum(1 for x in c if x["ok"] is True),
                "checked": sum(1 for x in c if x["ok"] is not None),
                "withdrawn": withdrawn.get(p.slug),
            }
        )
    return {
        "items": items,
        "n": len(items),
        "withdrawn": sum(1 for i in items if i["withdrawn"]),
        "source": SOURCE,
    }


def unpublish(slug: str, reason: str, *, actor: str = audit.ADMIN, reg: Registry | None = None) -> dict[str, Any]:
    reg = reg or get_registry()
    reason = reason.strip()
    if not reason:
        raise ModerationError(422, "validation_error", "say why the part is withdrawn")
    before = reg.withdrawal(slug)
    try:
        got = reg.withdraw(slug, reason, actor)
    except KeyError as exc:
        raise ModerationError(404, "part_not_found", f"no part {slug!r}") from exc
    audit.record(
        "part.unpublish", slug, actor=actor, before={"withdrawn": before}, after={"withdrawn": got}, note=reason
    )
    return {"slug": slug, "withdrawn": got}


def republish(slug: str, reason: str, *, actor: str = audit.ADMIN, reg: Registry | None = None) -> dict[str, Any]:
    reg = reg or get_registry()
    reason = reason.strip()
    if not reason:
        raise ModerationError(422, "validation_error", "say why the part goes back in search")
    if reg.get_part(slug) is None:
        raise ModerationError(404, "part_not_found", f"no part {slug!r}")
    before = reg.withdrawal(slug)
    if before is None:
        raise ModerationError(409, "not_withdrawn", f"{slug} is not withdrawn")
    reg.restore(slug)
    audit.record(
        "part.republish", slug, actor=actor, before={"withdrawn": before}, after={"withdrawn": None}, note=reason
    )
    return {"slug": slug, "withdrawn": None}
