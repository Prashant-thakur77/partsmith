"""Human review routes under `/api/v1/review`: the queue, a chain's detail, the person's decision, rule drafts and
judge-vs-person agreement. Reads are public; decisions and drafts (a model call) need the admin token.

Accept is a person's sign-off shown next to the code's verdict; nothing here sets `verified`. Review state lives under
`$PARTSMITH_HOME/reviews/`, never in a job's directory (a committed replay's least of all)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, Field

from services.api.auth import require_admin
from services.api.common import API, _svc, publish_job
from services.api.errors import ApiError
from services.api.uploads import clean_image
from services.common import blobs
from services.review import ledger as review_ledger
from services.review import rules as review_rules
from services.review import store

router = APIRouter(prefix=f"{API}/review", tags=["review"])


@contextmanager
def _mapped() -> Iterator[None]:
    """The store's refusals as the API's error envelope."""
    try:
        yield
    except store.ReviewError as exc:
        raise ApiError(exc.status, exc.code, exc.message) from exc


class PinIn(BaseModel):
    id: int | None = Field(None, ge=1, description="Optional; the server numbers pins without one")
    u: float = Field(ge=0.0, le=1.0, description="Across the rectified top photo, 0 = left edge, 1 = right edge")
    v: float = Field(ge=0.0, le=1.0, description="Down the rectified top photo, 0 = top edge, 1 = bottom edge")
    note: str = Field("", max_length=300)


class RuleIn(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    keep: bool = False
    source_pin: int | None = None


class DecisionRequest(BaseModel):
    action: Literal["accept", "improve", "reject"]
    pins: list[PinIn] = Field(default_factory=list, max_length=store.MAX_PINS)
    note: str = Field("", max_length=store.MAX_NOTE)
    reason: str = Field("", max_length=store.MAX_REASON)
    rules: list[RuleIn] = Field(default_factory=list, max_length=50)
    publish: bool = Field(False, description="Accept only: publish the part (best effort is labelled as accepted)")
    why: str = Field("", max_length=store.MAX_REASON, description="Why it matters (kept in the feedback log)")
    attachments: list[str] = Field(
        default_factory=list,
        max_length=store.MAX_ATTACHMENTS,
        description="Keys from POST /review/{job_id}/attachments: pasted screenshots or reference pictures",
    )


@router.get("/queue", summary="Finished fix jobs waiting for a person's review (latest round of each chain)")
def review_queue(
    include_replays: bool = True, limit: Annotated[int, Query(ge=1, le=200)] = 50
) -> dict[str, list[dict[str, Any]]]:
    return {"items": store.queue(limit, include_replays, svc=_svc())}


@router.get("/stats", summary="Judge vs person: agreement counts and Cohen's kappa, computed from the reviews")
def review_stats() -> dict[str, Any]:
    return store.stats()


@router.get("/feedback", summary="The feedback log: every send-back, rejection and accept, why, and what happened next")
def review_feedback(
    family: str | None = None,
    outcome: Literal["fixed", "better", "not_fixed", "waiting", "not_measured", "rejected", "accepted"] | None = None,
    by: Literal["person", "test"] | None = None,
) -> dict[str, Any]:
    """Read from the review chains; "what happened next" is measured by code (mismatch at the pin, or the round's
    worst gap, before and after the next round)."""
    return review_ledger.feedback(family=family, outcome=outcome, by=by, svc=_svc())


@router.get("/{job_id}", summary="A review chain: rounds, pins with before/after mismatch, verdicts, judge scorecards")
def review_detail(job_id: str) -> dict[str, Any]:
    with _mapped():
        return store.detail(job_id, svc=_svc())


@router.post("/{job_id}/rules/draft", summary="Draft one family rule per reviewer note (admin; a model call)")
def review_rules_draft(job_id: str, _admin: None = Depends(require_admin)) -> dict[str, Any]:
    with _mapped():
        return {"rules": review_rules.draft(job_id, svc=_svc())}


def _publisher() -> Callable[[str, str], str | None]:
    def publish(job_id: str, note: str) -> str | None:
        part = publish_job(job_id, ack=True, note=note)  # the person's accept is the acknowledgement
        return str(part["slug"]) if part.get("slug") else None

    return publish


@router.post("/{job_id}/attachments", summary="Upload a pasted screenshot or reference picture for a decision (admin)")
async def review_attachment(
    job_id: str,
    image: Annotated[UploadFile, File(description="JPEG, PNG or WebP, ≤ 25 MB; location metadata is removed")],
    _admin: None = Depends(require_admin),
) -> dict[str, str]:
    """Returns `{key, url}`; send the key in the decision's `attachments`. The image goes to the fixer with the notes."""
    with _mapped():
        store.detail(job_id, svc=_svc())  # 404 for an unknown job
    data, mime = clean_image(await image.read(), "image")
    key = blobs.put(data, ".jpg" if mime == "image/jpeg" else ".png")
    return {"key": key, "url": blobs.url(key)}


@router.post("/{job_id}", summary="Accept, improve (starts a reviewer round) or reject (admin)")
def review_decide(job_id: str, body: DecisionRequest, _admin: None = Depends(require_admin)) -> dict[str, Any]:
    """Send it to the chain's latest round. Improve needs a pin or a note; reject needs a reason. Returns the chain
    (`state`), the reviewer round started (`child_job`) and the published part (`part_slug`)."""
    with _mapped():
        return store.decide(
            job_id,
            body.action,
            pins=[p.model_dump(exclude_none=True) for p in body.pins],
            note=body.note,
            reason=body.reason,
            rules=[r.model_dump() for r in body.rules],
            publish=body.publish,
            publisher=_publisher(),
            attachments=body.attachments,
            why=body.why,
            svc=_svc(),
        )
