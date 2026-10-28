from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from eval.bypass import ATTACKS, CLAIMS, MAX_JPEG_BYTES, REFUSED_EXIT, format_demo, main, overlay_jpeg, run_suite
from services.geom_worker.sandbox import WarmPool


def test_every_lying_brain_attempt_is_blocked_by_code(tmp_path: Path) -> None:
    pool = WarmPool(size=1)
    try:
        rep = run_suite(pool, artifacts_dir=tmp_path)
    finally:
        pool.close()
    assert rep["attempts"] == len(ATTACKS) >= 12
    failed = [r for r in rep["rows"] if not r["blocked"]]
    assert not failed, failed
    assert {r["blocked_by"] for r in rep["rows"]} >= {"can_ship", "guards", "policy"}

    # judge-facing evidence: the claim, the verifier's own numbers, the gate's decision and a small overlay JPEG
    caught = {c["id"]: c for c in rep["caught"]}
    assert set(caught) == {"says_verified", "fake_break"}
    for aid, c in caught.items():
        assert c["claim"] == CLAIMS[aid] and "VERIFIED" in c["claim"]
        assert "no model call" in c["claim_source"]
        v = c["verifier"]
        assert v["verified"] is False and v["max_error_mm"] > v["threshold_mm"]
        assert c["export"]["ok"] is False and c["export"]["reason"]
        path = tmp_path / f"{aid}.jpg"
        assert path.is_file() and path.stat().st_size <= MAX_JPEG_BYTES
        img = Image.open(path)
        assert img.format == "JPEG" and list(img.size) == c["overlay_px"]


def test_overlay_jpeg_shrinks_to_the_byte_budget() -> None:
    noise = Image.effect_noise((1400, 1000), 120).convert("RGBA")  # incompressible worst case
    buf = io.BytesIO()
    noise.save(buf, "PNG")
    jpg = overlay_jpeg(buf.getvalue(), max_bytes=60_000)
    assert len(jpg) <= 60_000 and Image.open(io.BytesIO(jpg)).format == "JPEG"


def test_lie_demo_cli_prints_the_refusal_and_exits_non_zero(capsys: pytest.CaptureFixture[str]) -> None:
    # `make lie`: the non-zero exit is the success case (the export gate refused the lie)
    assert main(["--demo", "says_verified"]) == REFUSED_EXIT
    out = capsys.readouterr().out
    assert CLAIMS["says_verified"] in out
    assert "verified=False" in out and "vs limit 0.50 mm" in out
    assert "export     BLOCKED (" in out and "can_ship" in out


def test_lie_demo_reports_a_lie_that_got_through() -> None:
    rec = {
        "attack": "a",
        "claim": "VERIFIED",
        "verifier": {"verified": False, "status": "best_effort", "max_error_mm": 1.0, "threshold_mm": 0.5,
                     "failed_tests": []},
        "export": {"ok": True, "requires_ack": False, "reason": "verified", "gate": "g"},
    }  # fmt: skip
    text = format_demo(rec, 0.1)
    assert "ALLOWED" in text and "GOT THROUGH" in text


def test_lie_demo_rejects_unknown_attacks() -> None:
    with pytest.raises(SystemExit):
        main(["--demo", "no_such_attack"])
