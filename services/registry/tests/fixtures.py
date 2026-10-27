"""Shared test fixtures for the registry, API and MCP tests: no keys, no network, an isolated $PARTSMITH_HOME and
replay directory, and helpers that build registry parts straight from family templates (TEST DATA, not seeded parts)."""

from __future__ import annotations

import secrets
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from partsmith_schemas import DataOrigin, PartRecord, Validity, Verification, ViewMetrics
from partsmith_schemas.registry import Provenance

from services.agent import jobs, providers
from services.agent.providers import clients, mocks, retry
from services.agent.templates import get_template
from services.common import blobs
from services.geom_worker.program import code_sha, set_defaults
from services.registry import store

KEY_VARS = (
    "PROVIDER_MODE",
    "PROVIDER_RECORD",
    "OPEN_WEIGHTS_ONLY",
    "PROVIDER_FALLBACK_TO_MOCK",
    "MODEL_API_KEY",
    "BASETEN_API_KEY",
    "FIREWORKS_API_KEY",
    "TOGETHER_API_KEY",
    "GLIMMER_BASE_URL",
    "SAM3_OPEN_URL",
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Every test: mock providers, a fresh home, registry and job manager, replays under tmp."""
    for name in KEY_VARS:
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    monkeypatch.setenv("PARTSMITH_ENV_FILE", str(tmp_path / "no.env"))
    monkeypatch.setenv("PARTSMITH_HOME", str(home))
    monkeypatch.setenv("PARTSMITH_WARM_CAD", "0")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(retry, "sleep", lambda s: None)
    monkeypatch.setattr(jobs, "REPLAYS_DIR", tmp_path / "replays")
    monkeypatch.setattr(blobs, "REPLAY_BLOBS", tmp_path / "replays" / "_blobs")
    monkeypatch.setattr(store, "_registry", None)
    providers.reset_state()
    mocks.clear_mocks()
    try:
        from services.agent import service

        service.reset_manager(None)
    except ImportError:
        pass
    from services.registry import steer

    monkeypatch.setattr(steer, "_local_manager", None)
    steer._runs.clear()
    yield home
    providers.reset_state()
    mocks.clear_mocks()
    clients.set_http_transport(None)
    try:
        from services.agent import service

        service.reset_manager(None)
    except ImportError:
        pass


def make_part(
    template: str,
    slug: str | None = None,
    *,
    params: dict[str, float] | None = None,
    verified: bool = True,
    origin: DataOrigin = DataOrigin.synthetic,
    forked_from: str | None = None,
    max_error_mm: float = 0.12,
) -> PartRecord:
    """A registry record straight from a template (test data; the verification record is a stub)."""
    t = get_template(template)
    code = set_defaults(t.code, params or {})
    from services.geom_worker.program import parse_params

    specs = parse_params(code)
    return PartRecord(
        id="p_" + secrets.token_hex(4),
        slug=slug or template.replace("_", "-"),
        title=t.title,
        family=t.family,
        summary=t.summary,
        tags=list(t.tags),
        status="verified" if verified else "best_effort",
        params=specs,
        defaults={s.name: float(s.default) for s in specs},
        code=code,
        code_sha=code_sha(code),
        verification=Verification(
            verified=verified,
            status="verified" if verified else "best_effort",
            max_error_mm=max_error_mm,
            origin=origin,
            views=[
                ViewMetrics(
                    view="top",
                    iou=0.99 if verified else 0.9,
                    hausdorff_mm=max_error_mm,
                    hd95_mm=max_error_mm,
                    mean_mm=max_error_mm / 2,
                )
            ],
            validity=Validity(
                is_valid=True, single_solid=True, watertight=True, volume_mm3=1000.0, bbox_mm=(10.0, 10.0, 10.0)
            ),
            hashes={"code_sha256": code_sha(code), "mesh_sha256": "0" * 64},
            reasons=[] if verified else ["the top outline differs from the photo by up to 0.8 mm"],
        ),
        provenance=Provenance(origin=origin, created_by="test", forked_from=forked_from, note="TEST DATA"),
        created_at=time.time(),
    )


def add_part(template: str, slug: str | None = None, **kw: object) -> PartRecord:
    part = make_part(template, slug, **kw)  # type: ignore[arg-type]
    store.get_registry().upsert_part(part)
    return part
