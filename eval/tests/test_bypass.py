from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from eval.bypass import ATTACKS, CLAIMS, MAX_JPEG_BYTES, overlay_jpeg, run_suite
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
