"""Generate test-only fixtures for the web e2e suite (route-mocked; never imported by src/).

Geometry comes from real family templates through the worker's view.json exporter; images are synthetic
renders of the screen mat with a drawn part. Run from the repo root:

    uv run python apps/web/e2e/fixtures/generate.py
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from services.agent.templates import cable_clip, l_bracket
from services.geom_worker.export import view_json
from services.geom_worker.program import parse_params
from services.metrology.mats import get_mat, render_mat

OUT = Path(__file__).resolve().parent / "generated"
PX_PER_MM = 4.0


def params_of(mod: object) -> list[dict[str, object]]:
    src = Path(mod.__file__).read_text()  # type: ignore[attr-defined]
    return [p.model_dump() for p in parse_params(src)]


def defaults(mod: object) -> dict[str, float]:
    return {k: float(v[0]) for k, v in mod.PARAMS.items()}  # type: ignore[attr-defined]


def shape(mod: object, p: dict[str, float]):  # type: ignore[no-untyped-def]
    wp = mod.build(p)  # type: ignore[attr-defined]
    return wp.val() if hasattr(wp, "val") else wp


def write_view(name: str, mod: object, p: dict[str, float]) -> None:
    (OUT / f"view-{name}.json").write_text(json.dumps(view_json(shape(mod, p)), separators=(",", ":")))


def images() -> None:
    mat = get_mat("screen-m")
    grey = render_mat("screen-m", PX_PER_MM)
    photo = cv2.cvtColor(grey, cv2.COLOR_GRAY2BGR)
    cx, cy = mat.width_mm / 2 * PX_PER_MM, mat.height_mm / 2 * PX_PER_MM
    w, h = 40 * PX_PER_MM, 20 * PX_PER_MM
    rect = np.array([[cx - w / 2, cy - h / 2], [cx + w / 2, cy - h / 2], [cx + w / 2, cy + h / 2], [cx - w / 2, cy + h / 2]], np.int32)
    cv2.fillPoly(photo, [rect], (90, 98, 104))
    for dx in (-10, 10):
        cv2.circle(photo, (int(cx + dx * PX_PER_MM), int(cy)), int(2.25 * PX_PER_MM), (255, 255, 255), -1)
    cv2.imwrite(str(OUT / "photo.png"), photo)

    H, W = photo.shape[:2]

    def rgba() -> np.ndarray:
        return np.zeros((H, W, 4), np.uint8)

    mask = rgba()
    cv2.fillPoly(mask, [rect], (33, 106, 242, 110))
    cv2.imwrite(str(OUT / "mask.png"), mask)

    meas = rgba()
    cv2.line(meas, (int(cx - w / 2), int(cy + h / 2 + 18)), (int(cx + w / 2), int(cy + h / 2 + 18)), (20, 20, 20, 255), 2)
    cv2.putText(meas, "40.02 mm", (int(cx - 34), int(cy + h / 2 + 40)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20, 255), 2)
    cv2.imwrite(str(OUT / "measure.png"), meas)

    render = photo.copy()
    cv2.polylines(render, [rect + 2], True, (33, 106, 242), 2)
    cv2.imwrite(str(OUT / "render.png"), render)

    heat = rgba()
    cv2.polylines(heat, [rect], True, (60, 60, 230, 230), 4)
    cv2.imwrite(str(OUT / "heatmap.png"), heat)

    thumb = np.full((300, 400, 3), 245, np.uint8)
    cv2.rectangle(thumb, (110, 120), (290, 200), (150, 150, 146), -1)
    cv2.rectangle(thumb, (110, 120), (290, 200), (40, 40, 40), 2)
    cv2.imwrite(str(OUT / "thumb.png"), thumb)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lb = defaults(l_bracket)
    write_view("l-bracket", l_bracket, lb)
    write_view("l-bracket-variant", l_bracket, {**lb, "thickness": 5.0, "gusset_count": 0.0})
    write_view("cable-clip", cable_clip, defaults(cable_clip))
    meta = {
        "l-bracket": {
            "title": l_bracket.TITLE,
            "summary": l_bracket.SUMMARY,
            "tags": l_bracket.TAGS,
            "params": params_of(l_bracket),
            "defaults": lb,
            "code": Path(l_bracket.__file__).read_text(),
        },
        "cable-clip": {
            "title": cable_clip.TITLE,
            "summary": cable_clip.SUMMARY,
            "tags": cable_clip.TAGS,
            "params": params_of(cable_clip),
            "defaults": defaults(cable_clip),
            "code": Path(cable_clip.__file__).read_text(),
        },
    }
    (OUT / "templates.json").write_text(json.dumps(meta, indent=1))
    images()
    print(f"wrote fixtures to {OUT}")


def product() -> None:
    """Playground / Describe it fixtures from the real code (mock planner, real sandbox bakes), under a throwaway
    $PARTSMITH_HOME. `uv run python apps/web/e2e/fixtures/generate.py product` writes only these."""
    import os
    import sys
    import tempfile

    os.environ["PARTSMITH_HOME"] = tempfile.mkdtemp(prefix="ps-fixtures-")
    os.environ["PROVIDER_MODE"] = "mock"
    from services.agent.buy_or_print import print_plan
    from services.agent.templates import get_template
    from services.registry import describe, examples

    def scrub(rec: dict) -> dict:  # stable ids/times in fixtures; view URLs point at the fixture file route
        rec = json.loads(json.dumps(rec))
        rec["created_at"] = rec["updated_at"] = 1_793_100_000.0
        for e in rec.get("events", []):
            e["ts"] = 1_793_100_000.0
        if rec.get("bake"):
            rec["bake"]["view_url"] = "/api/v1/files/view-describe.json"
        return rec

    done = describe.start("a cable clip for a 6 mm cable, screws down with one M3 screw, 20 mm wide, 45 mm long")
    t = get_template("cable_clip")
    (OUT / "view-describe.json").write_text(json.dumps(view_json(shape(cable_clip, {**t.defaults, **done["bake"]["params"]})), separators=(",", ":")))
    asks = describe.start("a cable clip for a 6 mm cable, 20 mm wide")
    nofit = describe.start("a propeller with three blades")
    example = describe.example()
    bake = examples.bake_template("cable_clip", {}, ("view",))
    out = {
        "templates": examples.all_cards(),
        "detail": {"cable_clip": examples.template_detail(t)},
        "print_plan": print_plan(bake.facts) if bake.facts else None,
        "facts": bake.facts.model_dump(mode="json") if bake.facts else None,
        "ship_reason": examples.TEMPLATE_SHIP_REASON,
        "describe": {"done": scrub(done), "asks": scrub(asks), "no_fit": scrub(nofit), "example": scrub(example)},
    }
    out["describe"]["done"]["id"] = "d_261031_0000done"
    out["describe"]["asks"]["id"] = "d_261031_0000asks"
    out["describe"]["no_fit"]["id"] = "d_261031_000nofit"
    (OUT / "product.json").write_text(json.dumps(out, indent=1))
    print(f"wrote product fixtures to {OUT}", file=sys.stderr)


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["product"]:
        product()
    else:
        main()
        product()
