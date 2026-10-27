from __future__ import annotations

import base64
import io
from typing import Any

import numpy as np
import pytest
from partsmith_schemas.common import Measured
from partsmith_schemas.partspec import BaseProfile, BlindHole, DShaftBore, Family, PartSpec, SlotFeature, ThroughHole
from partsmith_schemas.verification import PartTest, Verification, ViewMetrics
from PIL import Image

from services.agent import providers
from services.agent.providers import clients, media
from services.media import coupon, preview, repair_card


def _png(rgb: np.ndarray) -> bytes:
    return media.encode_png(rgb.astype(np.uint8))


def test_mock_preview_is_deterministic_composite_with_label() -> None:
    photo = np.full((120, 160, 3), 90, np.uint8)
    render = np.full((60, 80, 3), 255, np.uint8)
    render[20:40, 30:50] = (0, 120, 255)  # the part; white is background
    a = preview.see_the_fix(_png(photo), _png(render), "white PLA")
    b = preview.see_the_fix(_png(photo), _png(render), "white PLA")
    assert a.image == b.image and a.mode == "mock" and a.label == "MOCK PREVIEW — not AI-generated"
    out = np.asarray(Image.open(io.BytesIO(a.image)).convert("RGB")).astype(int)
    assert out.shape == (120, 160, 3)
    assert out[60, 80, 2] > 150  # render blended in at the part (scaled 2x)
    assert tuple(out[110, 10]) == (90, 90, 90)  # background untouched
    assert out[2:10, :, 0].mean() > out[2:10, :, 2].mean() + 50  # red label banner
    assert "white PLA" in a.prompt


def test_live_preview_calls_muse_image(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    generated = _png(np.full((4, 4, 3), 1))
    calls: list[dict[str, object]] = []

    class FakeResponses:
        def create(self, **kw: object) -> dict[str, object]:
            calls.append(kw)
            return {"output": [{"type": "image_generation_call", "result": base64.b64encode(generated).decode()}]}

    class FakeClient:
        responses = FakeResponses()

    clients.set_client_factory(lambda base, key, timeout: FakeClient())
    photo, render = _png(np.zeros((8, 8, 3))), _png(np.ones((8, 8, 3)))
    res = preview.see_the_fix(photo, render, "matte black")
    assert res.mode == "live" and res.label == "AI preview" and res.image == generated and res.usd == 0.01
    content = calls[0]["input"][0]["content"]  # type: ignore[index]
    assert len(content) == 3 and content[1]["type"] == "input_image"


def _verification(verified: bool) -> Verification:
    return Verification(
        verified=verified,
        status="verified" if verified else "best_effort",
        reasons=["hole_1 within 0.08 mm"],
        views=[ViewMetrics(view="top", iou=0.981, hausdorff_mm=0.31, hd95_mm=0.2, mean_mm=0.08)],
        tests=[PartTest(id="t1", description="d", value=4.2, expected=4.2, tol=0.15, passed=True)],
        max_error_mm=0.31,
    )


def test_repair_card_pdf_contains_only_passed_in_numbers() -> None:
    card = repair_card.RepairCardData(
        title="Cupboard latch",
        family="latch",
        slug="cupboard-latch-a1",
        url_text="partsmith.app/p/cupboard-latch-a1",
        key_dims=[
            repair_card.KeyDim("Hole diameter", 4.2, "measured", 0.08),
            repair_card.KeyDim("Depth", None, "inferred"),
        ],
        verification=_verification(True),
        print_settings=repair_card.PrintSettings(orientation="flat face down"),
        job_id="job_123",
    )
    pdf = repair_card.make_repair_card(card)
    assert pdf.startswith(b"%PDF")
    text = pdf.decode("latin-1")
    for needle in (
        "Cupboard latch",
        "VERIFIED",
        "IoU 0.981",
        "Hausdorff 0.31 mm",
        "4.20 mm",
        "not measured",
        "1/1 passed",
    ):
        assert needle in text, needle
    assert "MOCK" not in text and "SYNTHETIC" not in text
    a4 = repair_card.make_repair_card(card, page="A4")
    assert b"/MediaBox [ 0 0 595.2756 841.8898 ]" in a4


def test_repair_card_badges_never_upgrade() -> None:
    badge, _ = repair_card.verification_lines(_verification(False))
    assert badge == "BEST EFFORT"
    assert repair_card.verification_lines(None)[0] == "NOT VERIFIED"
    card = repair_card.RepairCardData(title="x", family="clip", origin="synthetic", provider_mode="mock")
    text = repair_card.make_repair_card(card).decode("latin-1")
    assert "SYNTHETIC" in text and "MOCK MODELS" in text and "NOT VERIFIED" in text and "not specified" in text


def _spec() -> PartSpec:
    m = Measured
    return PartSpec(
        family=Family.bracket,
        title='Shelf "bracket"\nimport os',
        base_profile=BaseProfile(kind="rect", points_mm=[(0, 0), (40, 0), (40, 20), (0, 20)]),
        thickness=m(value=3.0),
        features=[
            ThroughHole(id="hole_1", center_mm=(8, 9), diameter=m(value=4.2)),
            ThroughHole(id="hole_2", center_mm=(30, 9), diameter=m(value=4.2)),  # duplicate size → tested once
            BlindHole(id="pin", center_mm=(20, 5), diameter=m(value=3.0), depth=m(value=2.0)),
            SlotFeature(id="slot_1", center_mm=(20, 15), length=m(value=10.0), width=m(value=3.2)),
            DShaftBore(id="shaft", diameter=m(value=6.0), flat_depth=m(value=1.0)),
        ],
    )


def test_coupon_from_partspec_is_policy_clean_and_parametric() -> None:
    from services.geom_worker.policy import check_code
    from services.geom_worker.program import parse_params

    code = coupon.coupon_from_partspec(_spec())
    assert check_code(code) == []
    imports = [ln for ln in code.splitlines() if "import" in ln and not ln.startswith("#")]
    assert imports == ["import cadquery as cq"]  # the model-written title cannot inject code
    names = [p.name for p in parse_params(code)]
    assert names == [
        "thickness",
        "clearance_step",
        "hole_1_d",
        "pin_d",
        "slot_1_w",
        "slot_1_l",
        "shaft_d",
        "shaft_flat",
    ]
    with pytest.raises(ValueError):
        coupon.coupon_program([])
    with pytest.raises(ValueError):
        coupon.coupon_program([coupon.CouponFeature("d", "d_bore", diameter_mm=4, flat_depth_mm=3)])


def test_coupon_builds_valid_solid_with_three_columns() -> None:
    code = coupon.coupon_program(
        [coupon.CouponFeature("hole", "hole", diameter_mm=4.0)], clearance_step_mm=0.2, thickness_mm=2.0
    )
    ns: dict[str, object] = {}
    exec(code, ns)  # trusted, generated by us; the sandbox runs model-written code
    shape = ns["result"].val()  # type: ignore[attr-defined]
    assert shape.isValid()
    import cadquery as cq

    edges: list[Any] = cq.Workplane().add(shape).edges("%CIRCLE").vals()
    radii = sorted(round(e.radius() * 2, 3) for e in edges if abs(e.Center().z - 2.0) < 1e-6)
    assert radii == [3.8, 4.0, 4.2]
    bb = shape.BoundingBox()
    assert bb.zmin == pytest.approx(0.0) and bb.zmax == pytest.approx(2.0)


def test_providers_left_in_mock_mode() -> None:
    assert providers.stage_mode("image") == "mock"
