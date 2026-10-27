"""The export gate: may this part leave PartSmith as a printable file?

One decision for every exit (job publish, job-part downloads, bundle.zip, MCP bake/get_part): verified ships; best
effort ships only after the caller acknowledges the plain-words reason (`ack=1`); failed or unverified never ships.
The verifier's `services.verifier.ship.can_ship` is the authority when it is installed; until then the same rule is
applied here from the `Verification` record, so callers never change.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from partsmith_schemas import PartRecord, Verification

Status = Literal["verified", "best_effort", "blocked"]


@dataclass
class ShipDecision:
    status: Status
    reason: str
    source: str  # "verifier.ship" or "registry.gate (fallback)"

    @property
    def needs_ack(self) -> bool:
        return self.status == "best_effort"

    def allowed(self, ack: bool) -> bool:
        return self.status == "verified" or (self.status == "best_effort" and ack)

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "reason": self.reason, "needs_ack": self.needs_ack, "source": self.source}


class ShipBlocked(Exception):
    """Raised when an export needs an acknowledgement (best effort) or is refused (failed/unverified)."""

    def __init__(self, decision: ShipDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


def _verifier_can_ship() -> Callable[..., Any] | None:
    try:
        mod = importlib.import_module("services.verifier.ship")
    except ImportError:
        return None
    fn = getattr(mod, "can_ship", None)
    return fn if callable(fn) else None


def _fallback(v: Verification | None) -> ShipDecision:
    src = "registry.gate (fallback)"
    if v is None:
        return ShipDecision("blocked", "No verification record: nothing checked this part against a photo.", src)
    if v.verified and v.status == "verified":
        err = f" (max error {v.max_error_mm:.2f} mm)" if v.max_error_mm is not None else ""
        return ShipDecision("verified", f"Verified{err}.", src)
    if v.status == "best_effort":
        err = f"max error {v.max_error_mm:.2f} mm" if v.max_error_mm is not None else "the error is unknown"
        why = "; ".join(v.reasons[:2]) or "it did not pass every check"
        return ShipDecision(
            "best_effort", f"Best effort, not verified: {err}; {why}. Print a test piece before relying on it.", src
        )
    return ShipDecision("blocked", "; ".join(v.reasons[:2]) or "The part failed verification.", src)


def decide(*, verification: Verification | None, job: Any = None, job_status: str | None = None) -> ShipDecision:
    """The decision for a job or a published part. Uses `services.verifier.ship.can_ship(verification, *, job_status,
    acknowledged_best_effort)` when installed (it also re-checks that a "verified" record agrees with its own numbers);
    otherwise the same rule from the record alone."""
    status = job_status or (str(job.summary.status) if job is not None else "done")
    fn = _verifier_can_ship()
    if fn is not None:
        try:
            res = fn(verification, job_status=status, acknowledged_best_effort=False)
        except TypeError:
            res = None
        if res is not None:
            ok = bool(getattr(res, "ok", False))
            needs_ack = bool(getattr(res, "requires_ack", False))
            reason = str(getattr(res, "reason", ""))
            st: Status = "best_effort" if needs_ack else "verified" if ok else "blocked"
            return ShipDecision(st, reason or _fallback(verification).reason, "verifier.ship")
    if status != "done":
        return ShipDecision("blocked", f"blocked: the job is {status}", "registry.gate (fallback)")
    return _fallback(verification)


def decide_part(part: PartRecord) -> ShipDecision:
    return decide(verification=part.verification)


def require(decision: ShipDecision, ack: bool) -> None:
    if not decision.allowed(ack):
        raise ShipBlocked(decision)
