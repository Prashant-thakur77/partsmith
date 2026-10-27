"""Lessons (PLAN §6.8): after each job, code extracts candidate lessons from what the loop actually measured.

Candidates go into the registry with status "candidate" and are never promoted here: promotion needs a human in the
Steer queue or a fit check / printed part that confirms it. Only promoted lessons are shown to the builder.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

MAX_PROMPT_LESSONS = 8


@dataclass(frozen=True)
class LessonCandidate:
    scope: str  # family name or "global"
    rule: str
    evidence: dict[str, Any]


def extract_candidates(
    *,
    job_id: str,
    family: str,
    template: str | None,
    first_values: Mapping[str, float],
    final_values: Mapping[str, float],
    iterations: Sequence[Mapping[str, Any]],
    verified: bool,
    strategy_switches: Sequence[str],
    max_error_mm: float | None,
    origin: str,
) -> list[LessonCandidate]:
    """Candidate lessons from one finished job. `iterations` are IterationEvent dicts (edits, hausdorff_mm, ...)."""
    out: list[LessonCandidate] = []
    base = {
        "job_id": job_id,
        "template": template,
        "origin": origin,
        "verified": verified,
        "max_error_mm": max_error_mm,
    }
    # Parameters the builder's first guess got wrong by more than 0.3 mm and the fix loop had to correct.
    for name, first in sorted(first_values.items()):
        final = final_values.get(name)
        if final is None or abs(final - first) < 0.3:
            continue
        edits = [
            e for it in iterations for e in it.get("edits", []) if isinstance(e, Mapping) and e.get("param") == name
        ]
        if not edits:
            continue
        out.append(
            LessonCandidate(
                scope=family,
                rule=(
                    f"{template or family}: the first build set {name} = {first:g}, the verified loop moved it to "
                    f"{final:g} ({final - first:+.2f}) — check {name} against the measurement before building."
                ),
                evidence={**base, "param": name, "first": first, "final": final, "n_edits": len(edits)},
            )
        )
    for sw in strategy_switches:
        out.append(
            LessonCandidate(
                scope=family,
                rule=f"{template or family}: strategy switched ({sw}) after two rounds without improvement.",
                evidence={**base, "switch": sw},
            )
        )
    if not verified and max_error_mm is not None:
        out.append(
            LessonCandidate(
                scope=family,
                rule=(
                    f"{template or family}: best effort only ({max_error_mm:.2f} mm) after "
                    f"{len(iterations)} rounds — this shape may need a new template knob."
                ),
                evidence=base,
            )
        )
    return out


def record(candidates: Sequence[LessonCandidate], registry: Any) -> list[str]:
    """Store candidates (status "candidate"); returns the lesson ids."""
    return [registry.add_lesson(c.scope, c.rule, c.evidence) for c in candidates]


def promoted_rules(registry: Any, family: str) -> list[str]:
    """Promoted lessons for a family (plus global ones), newest last, capped for the prompt."""
    rows = registry.lessons(scope=family, status="promoted")
    return [str(r["rule"]) for r in rows][-MAX_PROMPT_LESSONS:]


def format_for_prompt(rules: Sequence[str]) -> str:
    return "\n".join(f"- {r}" for r in rules) if rules else "- (none promoted yet)"
