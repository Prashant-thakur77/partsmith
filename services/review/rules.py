"""Rule drafts for accept: each note in a review chain → one general rule for the part's family (model proposes).

Stage `review_rules` (Spark 1.3; mock = the note itself, scoped to the family). A person edits and ticks the drafts;
only ticked ones are promoted (`store.decide`). The model calls are attached to the chain's latest job, except for a
committed replay, whose directory is never written: those calls are kept in the review file instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from services.agent import mock_brain, prompt_loader, providers
from services.agent.providers import ModelRequest, ProviderError
from services.review import store

RULE_MAX = 160
RULE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"rule": {"type": "string"}},
    "required": ["rule"],
    "additionalProperties": False,
}


def _notes(mgr: Any, state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every note in the chain: each pin's note (with its outcome) and each round's general note."""
    out: list[dict[str, Any]] = []
    for r in state["rounds"]:
        if r.get("decision") != "improve":
            continue
        got = store._outcomes(mgr, r.get("child_job"))
        for p in r.get("pins") or []:
            if str(p.get("note") or "").strip():
                out.append(
                    {
                        "note": p["note"],
                        "source_pin": int(p["id"]),
                        **{k: got.get(int(p["id"]), {}).get(k) for k in ("part_mm", "before_mm", "after_mm")},
                    }
                )
        if str(r.get("note") or "").strip():
            out.append({"note": r["note"], "source_pin": None, "part_mm": None, "before_mm": None, "after_mm": None})
    return out


def _mm(x: Any) -> str:
    return f"{float(x):.2f} mm" if isinstance(x, int | float) else "not measured"


def draft(job_id: str, *, svc: Any = None) -> list[dict[str, Any]]:
    """[{"text", "source_pin", "scope"}] — one draft per note in `job_id`'s chain ("skip" replies are left out)."""
    mgr = store._svc(svc).manager()
    _, root = store._locate(mgr, job_id)
    state = store._state(mgr, root)
    last = store._get(mgr, str(state["rounds"][-1]["job_id"]))
    family = store._family(last) or "custom"
    notes = _notes(mgr, state)
    if not notes:
        return []
    mock_brain.install(replace=False)
    replay = last is None or bool(last.summary.is_replay)
    kept: list[Any] = []
    emit = kept.append if replay else last.emit
    p = prompt_loader.load("review_rules")
    out: list[dict[str, Any]] = []
    with providers.job_context(str(last.id) if last is not None else root, emit):
        for n in notes:
            where = (
                f"pin {n['source_pin']} at ({n['part_mm'][0]:.1f}, {n['part_mm'][1]:.1f}) mm in the part frame"
                if n["part_mm"]
                else "the whole part (a general note)"
            )
            mismatch = f"before {_mm(n['before_mm'])}, after {_mm(n['after_mm'])}"
            dev, user = p.render(family=family, note=n["note"], where=where, mismatch=mismatch)
            req = ModelRequest(
                messages=[{"role": "developer", "content": dev}, {"role": "user", "content": user}],
                json_schema=RULE_SCHEMA,
                schema_name="review_rule",
                mock_context={"family": family, "note": n["note"]},
            )
            try:
                res = providers.complete("review_rules", req)
            except ProviderError:
                text = f"{family}: {n['note']}"  # the note itself, as the mock would; the person edits it
            else:
                text = str((res.json or {}).get("rule") or "").strip() if isinstance(res.json, Mapping) else ""
            if not text or text.lower() == "skip":
                continue
            out.append({"text": text[:RULE_MAX], "source_pin": n["source_pin"], "scope": family})
    if kept:
        with store._lock(root):
            st = store._state(mgr, root)
            st["model_calls"] = [
                *(st.get("model_calls") or []),
                *(e.model_dump(mode="json") if hasattr(e, "model_dump") else e for e in kept),
            ]
            if store._load(root) is not None:
                store._save(st)
    return out
