"""Repair passport ids: stable, short, versioned, typed-error tolerant; resolution order (no CAD, no network)."""

from __future__ import annotations

import pytest

from services.registry import passport as PP
from services.registry import presets
from services.registry.store import get_registry
from services.registry.tests.fixtures import add_part, make_part


def test_same_part_same_id_new_version_new_id() -> None:
    a = make_part("spacer", "spacer-a")
    b = make_part("spacer", "spacer-b")  # another record (id, slug, created_at) of the same program + values
    assert PP.part_id(a) == PP.part_id(b)
    assert len(PP.part_id(a)) == PP.ID_LEN and all(ch in PP.ALPHABET for ch in PP.part_id(a))
    bumped = a.model_copy(update={"version": 2})
    assert PP.part_id(bumped) != PP.part_id(a)
    assert PP.part_id(bumped, version=1) == PP.part_id(a)
    other = make_part("spacer", "spacer-a", params={"outer_d": 12.0})
    assert PP.part_id(other) != PP.part_id(a)  # other values are another part


def test_job_ids_are_stable_and_distinct() -> None:
    assert PP.job_id("j_261028_75795da3") == PP.job_id("j_261028_75795da3")
    assert PP.job_id("j_261028_75795da3") != PP.job_id("j_261028_8c786d43")


def test_normalize_reads_ids_the_way_people_type_them() -> None:
    pid = PP.encode(bytes(range(32)))
    assert PP.normalize(pid.lower()) == pid
    assert PP.normalize(f" {pid[:3]}-{pid[3:]} ") == pid
    assert PP.normalize("O1L2I3") == "011213"  # O → 0, I/L → 1 (Crockford)
    assert PP.normalize("ABC") is None and PP.normalize("ABCDEFG") is None and PP.normalize("ABCDU1") is None


def test_find_current_old_versions_and_jobs() -> None:
    p = add_part("spacer", "spacer-x")
    reg = get_registry()
    m = PP.find(PP.part_id(p), reg)
    assert m is not None and m.kind == "part" and m.part is not None and m.part.slug == "spacer-x" and m.version == 1
    v3 = p.model_copy(update={"version": 3})
    reg.upsert_part(v3)
    old = PP.find(PP.part_id(p, 1), reg)
    assert old is not None and old.version == 1 and old.part is not None and old.part.version == 3
    passport = PP.for_part(old.part, pid=PP.part_id(p, 1), version=1)
    assert passport.superseded and passport.current_version == 3 and "same program and values" in passport.notes[0]
    j = PP.find(PP.job_id("j_test_1"), reg, ["j_test_0", "j_test_1"])
    assert j is not None and j.kind == "job" and j.job == "j_test_1"
    assert PP.find("000000", reg, ["j_test_1"]) is None
    cur = PP.part_id(v3)
    typo = cur[:5] + ("0" if cur[5] != "0" else "1")
    assert cur in PP.closest(typo, reg)


def test_passport_for_part_carries_values_preset_status_and_gate() -> None:
    p = add_part("spacer", "spacer-y", verified=False)
    pid = PP.part_id(p)
    out = PP.for_part(p, pid=pid, spec={"fit": {"material": "PETG", "printer": "FDM_0_4"}})
    assert out.kind == "part" and out.url == f"/p/{pid}" and out.page_url == "/parts/spacer-y"
    assert out.values == {k: pytest.approx(v) for k, v in p.defaults.items()}
    assert out.preset.id == "petg-fdm-0.4" and out.preset.source == "job_spec"
    assert out.status == "best_effort" and not out.verified and out.ship.status == "best_effort" and out.ship.needs_ack
    assert out.bake_url == "/api/v1/parts/spacer-y/bake" and out.qr_svg_url.endswith(f"/passport/{pid}/qr.svg")
    assert out.fix_url.startswith("/fix?family=spacer&intent=") and pid in out.fix_url
    assert PP.for_part(p, pid=pid).preset.source == "default"


def test_preset_from_the_job_fit() -> None:
    assert presets.for_fit("PLA", "FDM_0_6") == "pla-fdm-0.6"
    assert presets.for_fit("anything", "SLA") == "resin-sla"
    assert presets.for_fit("TPU", "FDM_0_4") is None
    assert PP.preset_of({"fit": {"material": "TPU", "printer": "FDM_0_4"}}).id == presets.DEFAULT_ID
