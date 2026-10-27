"""measure_only scoring logic (pure parts) and a tiny end-to-end run on SYNTHETIC photos."""

import json
import math
from pathlib import Path

import pytest
import yaml
from partsmith_schemas.common import DataOrigin, Measured, Source
from partsmith_schemas.measurement import Hole, Measurements, ViewKind

from eval import measure_only as M


def _meas(view: str = "top", holes: list[tuple[float, tuple[float, float]]] | None = None) -> Measurements:
    def mm(v: float) -> Measured:
        return Measured(value=v, source=Source.measured, sigma_mm=0.1)

    return Measurements(
        view=ViewKind(view),
        origin=DataOrigin.synthetic,
        outline_mm=[(0, 0), (1, 0), (1, 1)],
        holes=[Hole(id=f"hole_{i + 1}", center_mm=c, diameter=mm(d)) for i, (d, c) in enumerate(holes or [])],
        length=mm(40.2),
        width=mm(19.9),
        thickness=mm(3.1) if view == "side" else None,
        area_mm2=700.0,
        part_to_mat=[[1, 0, 100], [0, 1, 50], [0, 0, 1]],
    )


def test_match_holes_by_centre_and_diameter() -> None:
    gt = [
        {"name": "hole_1.diameter", "value_mm": 4.0, "center_mat_mm": (90.0, 50.0)},
        {"name": "hole_2.diameter", "value_mm": 4.0, "center_mat_mm": (110.0, 50.0)},
    ]
    meas = [(3.9, (110.3, 50.1)), (4.1, (89.8, 50.0)), (2.0, (100.0, 60.0))]
    pairs, miss, extra = M.match_holes(gt, meas)
    assert sorted(pairs) == [(0, 1), (1, 0)] and miss == [] and extra == [2]
    pairs, miss, extra = M.match_holes(gt, [(4.0, (130.0, 50.0))])  # too far from any GT centre
    assert pairs == [] and miss == [0, 1] and extra == [0]
    pairs, miss, _ = M.match_holes(
        [{"name": "hole_1.diameter", "value_mm": 5.0}], [(3.0, (0, 0)), (4.8, (9, 9))], "diameter"
    )
    assert pairs == [(0, 1)] and miss == []


def test_score_measurements_by_name() -> None:
    m = _meas(holes=[(4.1, (-10.0, 0.0))])  # part frame → mat (90, 50)
    gt = [
        {"name": "length", "value_mm": 40.0},
        {"name": "width", "value_mm": 20.0},
        {"name": "hole_1.diameter", "value_mm": 4.0, "center_mat_mm": (90.2, 49.9)},
        {"name": "hole_2.diameter", "value_mm": 4.0, "center_mat_mm": (120.0, 49.9)},
    ]
    pairs, missed, extra = M.score_measurements(m, gt, "top")
    got = {g["name"]: v for g, v in pairs}
    assert got == {"length": 40.2, "width": 19.9, "hole_1.diameter": 4.1}
    assert missed == ["hole_2.diameter"] and extra == 0
    side_pairs, _, _ = M.score_measurements(_meas("side"), [{"name": "thickness", "value_mm": 3.0}], "side")
    assert side_pairs[0][1] == pytest.approx(3.1)
    none_pairs, none_missed, _ = M.score_measurements(None, gt, "top")
    assert none_pairs == [] and len(none_missed) == 4


def test_profile_and_gate() -> None:
    assert M.profile_of(3.4, 3.0) == "flat" and M.profile_of(10.5, 2.5) == "tall features"
    sec = {"accepted": {"n": 10, "mean_mm": 0.35}}
    empty = {"accepted": {"n": 0, "mean_mm": math.nan}}
    g = M.gate_verdict(
        {
            M.SRC_SYNTH: sec,
            M.SRC_REF_SYNTH: {"accepted": {"n": 4, "mean_mm": 0.5}},
            M.SRC_REF_REAL: empty,
            M.SRC_REAL: empty,
        }
    )
    assert g["synthetic"]["pass"] and not g["reference_objects"]["pass"] and not g["pass"]
    assert g["reference_objects"]["source"] == M.SRC_REF_SYNTH
    g2 = M.gate_verdict(
        {
            M.SRC_SYNTH: sec,
            M.SRC_REF_SYNTH: {"accepted": {"n": 4, "mean_mm": 0.9}},
            M.SRC_REF_REAL: {"accepted": {"n": 3, "mean_mm": 0.2}},
            M.SRC_REAL: empty,
        }
    )
    assert g2["reference_objects"]["source"] == M.SRC_REF_REAL and g2["pass"]  # real photos take precedence


def test_real_jobs_from_folders(tmp_path: Path) -> None:
    part = tmp_path / "p01"
    part.mkdir()
    (part / "top.jpg").write_bytes(b"x")
    (part / "side.jpg").write_bytes(b"x")
    (part / "gt.yaml").write_text(
        yaml.safe_dump(
            {
                "gt_source": "ruler",
                "dims": {"length": 42.0, "width": 18.5, "thickness": 3.0},
                "holes": [{"diameter": 4.0}],
            }
        )
    )
    other = tmp_path / "p02"
    other.mkdir()
    (other / "top.jpg").write_bytes(b"x")
    (other / "gt.yaml").write_text(yaml.safe_dump({"gt_source": "caliper", "dims": {"length": 1.0}}))
    jobs = M.real_part_jobs(tmp_path)
    assert [(j.sample_id, j.view) for j in jobs] == [("p01", "top"), ("p01", "side")]
    top = jobs[0]
    assert top.thickness_mm == 3.0 and top.match_holes_by == "diameter" and top.origin == "real"
    assert [g["name"] for g in top.gt] == ["length", "width", "hole_1.diameter"]
    assert all(g["tol_mm"] == 0.5 for g in top.gt)
    ref = tmp_path / "reference_objects" / "id1_card"
    ref.mkdir(parents=True)
    (ref / "a.jpg").write_bytes(b"x")
    rj = M.real_reference_jobs(tmp_path)
    assert len(rj) == 1 and rj[0].source == M.SRC_REF_REAL and {g["name"] for g in rj[0].gt} == {"length", "width"}
    assert M.real_reference_jobs(tmp_path / "missing") == [] and M.real_part_jobs(tmp_path / "missing") == []


def test_shape_from_meta_uses_user_knowledge_only() -> None:
    assert M.shape_from_meta("AA cell (lying on its side) (synthetic, clean)", "", "reference", "top") == "round"
    assert M.shape_from_meta("Caster wheel (synthetic, clean)", "", "wheel", "side") == "round"
    assert M.shape_from_meta("Caster wheel (synthetic, clean)", "", "wheel", "top") == "prism"
    assert M.shape_from_meta("L-bracket", "", "bracket", "side") == "prism"


def test_expected_rejections_are_not_errors() -> None:
    ok = M.PhotoRow(M.SRC_SYNTH, "a", "top", "clean", "clip", True, True, None, 2, 2)
    rej = M.PhotoRow(
        M.SRC_SYNTH,
        "b",
        "top",
        "white-on-light",
        "clip",
        True,
        False,
        "blends",
        2,
        2,
        expect_reject=True,
        failed_checks=["contrast"],
    )
    missed = M.PhotoRow(M.SRC_SYNTH, "c", "top", "white-on-light", "clip", True, True, None, 2, 2, expect_reject=True)
    dims = [
        M.DimRow(M.SRC_SYNTH, sid, "top", "length", 40.0, 40.0 + e, e, acc, profile="flat")
        for sid, e, acc in (("a", 0.1, True), ("b", 5.0, False), ("c", 3.0, True))
    ]
    rep = M.build_report([ok, rej, missed], dims, None, seed=0)
    sec = rep["sections"][M.SRC_SYNTH]
    assert sec["expected_rejections"]["k"] == 1 and sec["expected_rejections"]["n"] == 2
    assert sec["expected_rejections"]["missed"] == ["c"]
    assert sec["n_photos"] == 1 and sec["accepted"]["n"] == 1 and sec["all_detected"]["n"] == 1
    assert sec["top_view_split"]["top view, flat parts"]["n"] == 1
    reasons = [f["reason"] for f in rep["failures"]]
    assert len(reasons) == 1 and reasons[0].startswith("missed rejection")
    assert M.TOP_SPLIT_NOTE in M.to_markdown(rep)


def test_report_marks_empty_sources_pending() -> None:
    rep = M.build_report([], [], None, seed=0)
    md = M.to_markdown(rep)
    assert md.count("**pending**") == 4 and "FAIL" in md
    assert rep["sections"][M.SRC_REAL]["gt_source"] == "ruler (±0.5 mm)"


@pytest.mark.slow
def test_tiny_end_to_end(tmp_path: Path) -> None:
    from tools.synth import make_dataset

    make_dataset(tmp_path / "bench", n=2, n_reference=1, seed=4, presets=["clean"], size=(1600, 1200))
    rep = M.run_bench(
        bench_dir=tmp_path / "bench",
        real_dir=tmp_path / "real",
        n=2,
        n_reference=1,
        n_reject=0,
        seed=4,
        jobs=1,
        write_manifest=tmp_path / "bench_manifest.json",
        log=lambda s: None,
    )
    # the existing bench was made with other settings (size) but the same seed/n: it is reused, not re-rendered
    assert rep["sections"][M.SRC_SYNTH]["n_photos"] >= 2
    assert rep["sections"][M.SRC_REF_SYNTH]["n_photos"] >= 1
    jp, mp = M.write_report(rep, tmp_path / "out")
    assert json.loads(jp.read_text())["bench"] == "measure_only" and "Phase 1 exit gate" in mp.read_text()
    man = json.loads((tmp_path / "bench_manifest.json").read_text())
    assert man["origin"] == "synthetic" and len(man["samples"]) == 3
