"""Admin console routes under `/api/v1/admin` (all need the admin token): the overview, the audit log, registry
moderation and the taught-rule switches. Every number is computed by `services/admin` from stored data."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from services.admin import audit, moderation, overview
from services.admin import rules as taught
from services.api.auth import require_admin
from services.api.common import API, _svc
from services.api.errors import ApiError

router = APIRouter(prefix=f"{API}/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@contextmanager
def _mapped() -> Iterator[None]:
    try:
        yield
    except (moderation.ModerationError, taught.RuleError) as exc:
        raise ApiError(exc.status, exc.code, exc.message) from exc


class ReasonRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500, description="Why; kept in the audit log")


def _svc_or_none() -> Any:
    try:
        return _svc()
    except ApiError:
        return None


@router.get("/overview", summary="Site overview: jobs, pass rate, errors, reviews, parts, requests, cost (admin)")
def admin_overview() -> dict[str, Any]:
    return overview.overview(_svc_or_none())


@router.get("/audit", summary="The audit log of admin actions, newest first (admin)")
def admin_audit(
    limit: Annotated[int, Query(ge=1, le=audit.MAX_LIMIT)] = 100,
    action: str | None = None,
    target: str | None = None,
) -> dict[str, Any]:
    return audit.read(limit, action=action, target=target)


@router.get("/parts", summary="Every part with its publish criteria checked by code (admin)")
def admin_parts() -> dict[str, Any]:
    return moderation.parts()


@router.post("/parts/{slug}/unpublish", summary="Take a part out of search; it stays reachable by slug (admin)")
def admin_unpublish(slug: str, body: ReasonRequest) -> dict[str, Any]:
    with _mapped():
        return moderation.unpublish(slug, body.reason)


@router.post("/parts/{slug}/republish", summary="Put a withdrawn part back in search (admin)")
def admin_republish(slug: str, body: ReasonRequest) -> dict[str, Any]:
    with _mapped():
        return moderation.republish(slug, body.reason)


@router.get("/rules", summary="Taught rules and fixed feedback given to new jobs, with the jobs that used them (admin)")
def admin_rules() -> dict[str, Any]:
    return taught.list_rules(_svc_or_none())


@router.post("/rules/{rule_id:path}/disable", summary="Switch a taught rule off: no longer put into prompts (admin)")
def admin_rule_disable(rule_id: str, body: ReasonRequest) -> dict[str, Any]:
    with _mapped():
        return taught.disable(rule_id, body.reason, svc=_svc_or_none())


@router.post("/rules/{rule_id:path}/enable", summary="Switch a taught rule back on (admin)")
def admin_rule_enable(rule_id: str, body: ReasonRequest) -> dict[str, Any]:
    with _mapped():
        return taught.enable(rule_id, body.reason, svc=_svc_or_none())
