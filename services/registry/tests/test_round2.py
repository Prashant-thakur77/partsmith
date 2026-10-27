from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import pytest
from PIL import Image

from services.registry import batches, bundle, catalog, gate, presets, share_card
from services.registry import parts as P
from services.registry.publish import publish_part
from services.registry.store import ROLE_REFERENCE_TAG, get_registry
from services.registry.tests.fixtures import add_part, make_part


def test_product_names_and_cleanup_of_demo_slugs() -> None:
    latch = make_part("cupboard_latch", "demo-cupboard-latch", params={"length": 52.0})
    assert catalog.product_name(latch) == ("Cupboard door latch, 52 mm", "cupboard-door-latch-52mm")
    knob = make_part("knob", "x", params={"diameter": 30.8})
    assert catalog.product_name(knob) == ("Control knob, 30.8 mm", "control-knob-31mm")
    reg = get_registry()
    for p in (latch, make_part("spacer", "demo-ref-id1-card")):
        reg.upsert_part(p)
    moved = catalog.cleanup()
    assert moved["demo-cupboard-latch"] == "cupboard-door-latch-52mm"
    ref = reg.get_part(moved["demo-ref-id1-card"])
    assert ref is not None and ROLE_REFERENCE_TAG in ref.tags and ref.title.startswith("Reference object")
    assert not [s for s in reg.slugs() if s.startswith("demo-")]
    assert catalog.cleanup() == {}  # idempotent
    assert [p.slug for p in reg.search("", role="part")[0]] == ["cupboard-door-latch-52mm"]
    assert reg.stats()["reference"] == 1
    assert {f["family"] for f in reg.families(include_reference=False)} == {"latch"}


def test_reference_objects_are_named_from_the_sample_not_the_model() -> None:
    guessed = make_part("battery_cover", "x").model_copy(update={"title": "Battery compartment cover"})
    title, slug = catalog.product_name(guessed, reference=True, known_title="Full-size SD card (synthetic, clean)")
    assert (title, slug) == ("Reference object — Full-size SD card", "reference-full-size-sd-card")
    _, slug = catalog.product_name(
        guessed, reference=True, known_title="AA cell (lying on its side) (synthetic, clean)"
    )
    assert slug == "reference-aa-cell"


def test_fit_presets_touch_only_internal_fits() -> None:
    part = make_part("cable_clip")
    values, changes = presets.apply("petg-fdm-0.4", part.params, part.defaults)
    changed = {c["param"] for c in changes}
    assert changed == {"cable_d", "hole_d"}
    assert values["cable_d"] == pytest.approx(6.25) and values["hole_d"] == pytest.approx(3.75)
    assert values["length"] == part.defaults["length"] and values["width"] == part.defaults["width"]
    rows = presets.for_part(part.params, part.defaults)
    assert {r["id"] for r in rows} == set(presets.BY_ID) and all(r["changes"] for r in rows)
    with pytest.raises(KeyError):
        presets.apply("nylon", part.params, part.defaults)


def test_gate_uses_the_verifier_rule() -> None:
    ok = gate.decide_part(make_part("spacer"))
    assert ok.status == "verified" and ok.allowed(False)
    best = gate.decide_part(make_part("spacer", verified=False, max_error_mm=0.8))
    assert best.status == "best_effort" and not best.allowed(False) and best.allowed(True)
    assert "coupon" in best.reason.lower() or "best effort" in best.reason.lower()
    stub = make_part("spacer")
    assert stub.verification is not None
    stub.verification.hashes = {}  # a "verified" record that does not hold up is refused
    assert gate.decide_part(stub).status == "blocked"
    none = make_part("spacer")
    none.verification = None
    assert gate.decide(verification=None, job_status="done").status == "blocked"
    with pytest.raises(gate.ShipBlocked):
        gate.require(best, ack=False)


def test_bundle_zip_contents() -> None:
    part = add_part("spacer", "m3-spacer")
    values, info = presets.apply("pla-fdm-0.4", part.params, {**part.defaults, "height": 12.0}), None
    data = bundle.build_bundle(part, values[0], gate.decide_part(part), preset=info)
    z = zipfile.ZipFile(io.BytesIO(data))
    names = {n.split("/", 1)[1] for n in z.namelist()}
    assert names == {"README.md", "part.py", "part.step", "part.stl", "part.3mf", "verification.json", "LICENSE",
                     "index.html"}  # fmt: skip
    py = z.read("m3-spacer/part.py").decode()
    assert '"height": (12.0' in py and '"bore_d": (3.6' in py  # baked values + PLA preset on the bore
    ver = json.loads(z.read("m3-spacer/verification.json"))
    import hashlib

    assert ver["files_sha256"]["part.stl"] == hashlib.sha256(z.read("m3-spacer/part.stl")).hexdigest()
    assert ver["ship"]["status"] == "verified" and ver["verification"]["verified"] is True
    readme = z.read("m3-spacer/README.md").decode()
    assert "How to print" in readme and "CC-BY-4.0" in readme and "Measured vs not measured" in readme
    html = z.read("m3-spacer/index.html").decode()
    assert '<script id="view-data" type="application/json">' in html and "three.module.js" in html
    assert "CC-BY-4.0" in z.read("m3-spacer/LICENSE").decode()


def test_share_card_png() -> None:
    part = add_part("hook", "wall-hook")
    _t1, t2 = P.ensure_thumbnail(part)
    from services.common import blobs

    key = share_card.card_key(part, t2.rsplit("/", 1)[-1], "partsmith.dev/parts/wall-hook")
    img = Image.open(io.BytesIO(blobs.get(key)))
    assert img.size == (1200, 630)
    assert share_card.status_text(part)[0] == "Verified · 0.12 mm"
    assert share_card.status_text(make_part("hook", verified=False, max_error_mm=0.8))[0] == "Best effort · 0.80 mm"
    assert share_card.card_key(part, t2.rsplit("/", 1)[-1], "partsmith.dev/parts/wall-hook") == key  # cached


def test_batches_rows_and_sheet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARTSMITH_PRICE_PER_G_INR", "4")
    b = batches.create("Saturday", [{"name": "Asha", "contact": "98…", "jobs": ["j_1", "j_2"]}, {"name": "Ravi"}])
    batches.add_job(b["id"], "Ravi", "j_3")
    info: dict[str, dict[str, Any]] = {
        "j_1": {"title": "Cupboard latch", "status": "done", "verified": True, "max_error_mm": 0.31,
                "origin": "real", "facts": {"mass_g_pla": 5.0, "orientation": "-Z: flat", "supports_needed": False,
                                            "print_minutes_est": 22.0}},
        "j_2": {"title": "Knob", "status": "done", "verified": False, "max_error_mm": 0.9, "origin": "synthetic",
                "facts": None},
    }  # fmt: skip
    rows = batches.rows(batches.get(b["id"]), info.get)
    assert [r["job_id"] for r in rows] == ["j_1", "j_2", "j_3"]
    assert rows[0]["price_inr"] == 20.0 and rows[1]["price_inr"] is None and rows[2]["title"] == "(unknown job)"
    pdf = batches.sheet_pdf(batches.get(b["id"]), info.get)
    assert pdf[:5] == b"%PDF-" and b"Asha" in pdf and b"VERIFIED 0.31 mm" in pdf and b"INR 20" in pdf
    assert batches.list_batches()[0]["jobs"] == 3
    with pytest.raises(KeyError):
        batches.get("b_nope")


def test_publish_part_keeps_reference_role_out_of_matching() -> None:
    a = add_part("clip", "shelf-clip", params={"hole_d": 4.5})
    ref = make_part("l_bracket", "reference-bracket")
    ref.tags.append(ROLE_REFERENCE_TAG)
    publish_part(ref, render=False)
    assert [p.slug for p, _ in P.matching(a.slug)] == []
