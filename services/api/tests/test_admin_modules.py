"""services/admin units: the audit file, percentiles, store-level withdrawal and the disabled-rule prompt filter."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from services.admin import audit, overview
from services.admin import rules as taught
from services.registry.store import get_registry
from services.registry.tests.fixtures import add_part


def test_audit_appends_and_tolerates_a_missing_or_broken_file() -> None:
    assert audit.read()["items"] == []  # no file yet
    audit.record("x.one", "t1", before={"a": 1}, after={"a": 2}, numbers={"n": 3})
    with audit.path().open("a", encoding="utf-8") as fh:
        fh.write("{not json\n\n")
    audit.record("x.two", "t2", actor="test", note="why")
    got = audit.read()
    assert [i["action"] for i in got["items"]] == ["x.two", "x.one"] and got["actions"] == ["x.one", "x.two"]
    assert got["items"][0]["actor"] == "test" and got["items"][1]["actor"] == "admin token"
    assert got["items"][1]["numbers"] == {"n": 3}
    assert audit.read(1)["items"][0]["action"] == "x.two" and audit.read(1)["total"] == 2
    lines = audit.path().read_text().splitlines()
    assert len(lines) == 4  # appended, never rewritten


def test_audit_is_thread_safe() -> None:
    import threading

    ts = [threading.Thread(target=lambda i=i: audit.record("t", str(i))) for i in range(40)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert audit.read(1000)["total"] == 40


def test_percentile_nearest_rank() -> None:
    assert overview.percentile([], 50) is None
    assert overview.percentile([3.0], 90) == 3.0
    xs = [float(x) for x in range(1, 11)]
    assert overview.percentile(xs, 50) == 5.0 and overview.percentile(xs, 90) == 9.0


def test_reasons_group_case_and_spacing_apart_by_reviewer() -> None:
    items = [
        {"by": "person", "kind": "pin", "what": "Hole too small"},
        {"by": "person", "kind": "note", "what": "hole  too small."},
        {"by": "person", "kind": "accept", "what": "accepted"},
        {"by": "test", "kind": "reject", "what": "scripted"},
    ]
    r = overview.reasons(items)
    assert r["person"] == {"n": 2, "top": [{"reason": "Hole too small", "count": 2}]}
    assert r["test"]["top"] == [{"reason": "scripted", "count": 1}]


def test_store_withdraw_hides_from_public_search_only() -> None:
    reg = get_registry()
    add_part("spacer", "s-one")
    add_part("hook", "h-one")
    reg.withdraw("s-one", "bad", "admin token")
    assert [p.slug for p in reg.search("", role="part")[0]] == ["h-one"]
    assert {p.slug for p in reg.search("")[0]} == {"s-one", "h-one"}  # internal callers (dedupe, lineage) still see it
    assert {p.slug for p in reg.search("", role="part", include_withdrawn=True)[0]} == {"s-one", "h-one"}
    assert reg.get_part("s-one") is not None and reg.withdrawal("s-one")["reason"] == "bad"  # type: ignore[index]
    with pytest.raises(KeyError):
        reg.withdraw("nope", "x", "admin token")
    assert reg.restore("s-one") is True and reg.restore("s-one") is False
    assert reg.withdrawn() == {}


def _fake_run(tmp: Any, family: str = "spacer") -> Any:
    from services.agent.orchestrator import FixRun

    written: dict[str, Any] = {}
    fake = SimpleNamespace(
        spec=SimpleNamespace(family=SimpleNamespace(value=family)),
        _registry=get_registry,
        lessons_used=[],
        feedback_used=[],
        job=SimpleNamespace(write_json=lambda name, data: written.__setitem__(name, data)),
        opts=SimpleNamespace(review=None),
    )
    return fake, written, FixRun


def test_a_disabled_rule_is_not_put_into_prompts(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    reg = get_registry()
    keep = reg.add_lesson("spacer", "spacer: keep me", {})
    off = reg.add_lesson("spacer", "spacer: switch me off", {})
    for lid in (keep, off):
        reg.set_lesson_status(lid, "promoted", "reviewer")
    fake, written, FixRun = _fake_run(tmp_path)
    assert [r["id"] for r in FixRun.family_rules(fake)] == [keep, off]
    taught.disable(off, "made fits worse")
    fake, written, FixRun = _fake_run(tmp_path)
    rows = FixRun.family_rules(fake)
    assert [r["id"] for r in rows] == [keep]
    assert written["lessons_used.json"]["lesson_ids"] == [keep]  # not recorded as given either
    taught.enable(off, "try again")
    fake, _, FixRun = _fake_run(tmp_path)
    assert [r["id"] for r in FixRun.family_rules(fake)] == [keep, off]


def test_disabled_feedback_is_not_put_into_prompts(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from services.review import ledger

    entries = [
        {"id": "r1/1/pin1", "family": "spacer", "what": "move the hole left", "why": "", "before_mm": 0.9,
         "after_mm": 0.2, "by": "person", "outcome": "fixed", "kind": "pin", "used_in": {}},
        {"id": "r2/1/note2", "family": "spacer", "what": "make it thicker", "why": "", "before_mm": None,
         "after_mm": None, "by": "person", "outcome": "fixed", "kind": "note", "used_in": {}},
    ]  # fmt: skip
    monkeypatch.setattr(ledger, "for_prompt", lambda family, **kw: list(entries))
    monkeypatch.setattr(ledger, "feedback", lambda **kw: {"items": list(entries), "counts": {}, "families": []})
    taught.disable("r1/1/pin1", "the hole was right")
    fake, written, FixRun = _fake_run(tmp_path)
    lines = FixRun.past_feedback(fake)
    assert len(lines) == 1 and "make it thicker" in lines[0]
    assert written["feedback_used.json"]["ids"] == ["r2/1/note2"]
