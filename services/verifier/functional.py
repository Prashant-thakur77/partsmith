"""Functional probes: "will it actually work?" checks on the model, in plain words.

All probes are informational (PartTest priority P1): they never block ``verified``, which stays a statement about
matching the measured part. They answer the next question a user has:

- Screw / pin: for every round through-hole up to 7.6 mm (larger ones are bores), which metric screws pass, using ISO 273 clearance-hole diameters
  (close and normal fit), and the radial clearance in mm. "M3 screw passes (normal fit), 0.20 mm radial clearance".
- Interfaces: a part program may declare mating interfaces with ``interfaces(p)`` (where to probe, along which axis,
  and the standard mating sizes, e.g. panel thicknesses or shaft diameters). The gap is MEASURED on the solid by our
  ray casts (the program only says where to look), and the largest standard mate that fits is reported with its
  clearance class.
- Printability: overhang share in the best axis-aligned orientation, and the thinnest feature against 2 x nozzle.

Clearance classes (diametral clearance c = gap - mate, for FDM prints): c < 0 does not fit; 0-0.1 mm press fit;
0.1-0.3 mm sliding fit; 0.3-0.6 mm loose fit; above 0.6 mm very loose.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from partsmith_schemas.verification import PartTest

from services.verifier.solid_features import ModelHole

# ISO 273 clearance holes: nominal, close fit, normal fit (mm).
SCREWS: dict[str, tuple[float, float, float]] = {
    "M2": (2.0, 2.2, 2.4),
    "M2.5": (2.5, 2.7, 2.9),
    "M3": (3.0, 3.2, 3.4),
    "M4": (4.0, 4.3, 4.5),
    "M5": (5.0, 5.3, 5.5),
    "M6": (6.0, 6.4, 6.6),
}
NOZZLE_MM = 0.4
MIN_FEATURE_MM = 2 * NOZZLE_MM
OVERHANG_OK_SHARE = 0.10  # above this share of the surface, plan for supports
ROUND_COVERAGE_DEG = 350.0
SCREW_HOLE_MAX_MM = SCREWS["M6"][2] + 1.0  # larger round holes are bores or lightening holes, not screw holes


@dataclass
class FunctionalProbe:
    id: str
    kind: str  # "screw" | "interface" | "printability"
    text: str  # plain words, shown next to a tick or a cross
    passed: bool
    value_mm: float | None = None
    expected_mm: float | None = None
    clearance_mm: float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fit_class(clearance_mm: float) -> str:
    """Name of the fit for a diametral clearance (gap - mate)."""
    if clearance_mm < 0:
        return "does not fit"
    if clearance_mm < 0.1:
        return "press fit"
    if clearance_mm <= 0.3:
        return "sliding fit"
    if clearance_mm <= 0.6:
        return "loose fit"
    return "very loose"


def screw_probe(hole_id: str, diameter_mm: float) -> FunctionalProbe:
    """Which metric screws pass a round through-hole of `diameter_mm`."""
    passing: list[dict[str, Any]] = []
    for name, (nominal, close, normal) in SCREWS.items():
        if diameter_mm + 1e-6 >= close:
            fit = "normal fit" if diameter_mm + 1e-6 >= normal else "close fit"
            passing.append({"screw": name, "fit": fit, "radial_clearance_mm": round((diameter_mm - nominal) / 2, 3)})
    details: dict[str, Any] = {"diameter_mm": round(diameter_mm, 3), "passing": passing}
    if not passing:
        tight = [n for n, (nom, _, _) in SCREWS.items() if diameter_mm > nom]
        hint = f"; {tight[-1]} would be a tight self-tapping fit" if tight else ""
        return FunctionalProbe(
            f"probe.{hole_id}.screw",
            "screw",
            f"{hole_id}: no metric screw from M2 up passes freely (hole Ø{diameter_mm:.2f} mm){hint}",
            False,
            diameter_mm,
            SCREWS["M2"][1],
            None,
            details,
        )
    best = passing[-1]
    nominal, close, normal = SCREWS[best["screw"]]
    return FunctionalProbe(
        f"probe.{hole_id}.screw",
        "screw",
        f"{hole_id}: {best['screw']} screw passes ({best['fit']}), {best['radial_clearance_mm']:.2f} mm radial clearance",
        True,
        diameter_mm,
        close,
        best["radial_clearance_mm"],
        details,
    )


def interface_probe(itf: Mapping[str, Any]) -> FunctionalProbe:
    """Largest declared standard mate that fits the measured gap, with its clearance class."""
    iid, label, mate = str(itf.get("id")), str(itf.get("label", "")), str(itf.get("mate_label", "part"))
    gap = itf.get("gap_mm")
    mates = sorted(float(m) for m in itf.get("mates", []))
    if gap is None:
        note = itf.get("note") or "could not be measured"
        return FunctionalProbe(f"probe.{iid}", "interface", f"{label}: {note}", False, details=dict(itf))
    fits = [m for m in mates if gap - m >= 0]
    rows = [{"mate_mm": m, "clearance_mm": round(gap - m, 3), "fit": fit_class(gap - m)} for m in mates]
    details = {"gap_mm": round(float(gap), 3), "mates": rows}
    if not fits:
        return FunctionalProbe(
            f"probe.{iid}",
            "interface",
            f"{label}: {gap:.2f} mm — no standard {mate} in the list fits",
            False,
            float(gap),
            mates[0] if mates else None,
            None,
            details,
        )
    m = fits[-1]
    c = float(gap) - m
    return FunctionalProbe(
        f"probe.{iid}",
        "interface",
        f"{label}: a {m:g} mm {mate} fits, {c:.2f} mm clearance ({fit_class(c)})",
        True,
        float(gap),
        m,
        round(c, 3),
        details,
    )


def printability_probes(
    min_wall_mm: float | None, overhang_mm2: float | None, area_mm2: float | None, orientation: str | None
) -> list[FunctionalProbe]:
    out: list[FunctionalProbe] = []
    if min_wall_mm is not None:
        ok = min_wall_mm >= MIN_FEATURE_MM
        out.append(
            FunctionalProbe(
                "probe.min_feature",
                "printability",
                f"thinnest feature {min_wall_mm:.2f} mm "
                + (
                    f"≥ {MIN_FEATURE_MM:g} mm (2 × 0.4 mm nozzle)"
                    if ok
                    else f"< {MIN_FEATURE_MM:g} mm: too thin for a 0.4 mm nozzle"
                ),
                ok,
                min_wall_mm,
                MIN_FEATURE_MM,
            )
        )
    if overhang_mm2 is not None and area_mm2:
        share = overhang_mm2 / area_mm2
        ok = share <= OVERHANG_OK_SHARE
        where = f" ({orientation})" if orientation else ""
        text = f"{100 * share:.0f} % of the surface overhangs more than 45° in the best orientation{where}" + (
            "; prints without supports" if overhang_mm2 <= 4.0 else "; small overhangs" if ok else "; needs supports"
        )
        out.append(
            FunctionalProbe(
                "probe.overhang",
                "printability",
                text,
                ok,
                None,
                None,
                None,
                {"overhang_mm2": round(overhang_mm2, 2), "share": round(share, 4)},
            )
        )
    return out


def run_probes(
    holes: Sequence[tuple[str, ModelHole]],
    interfaces: Sequence[Mapping[str, Any]],
    *,
    min_wall_mm: float | None = None,
    overhang_mm2: float | None = None,
    area_mm2: float | None = None,
    orientation: str | None = None,
) -> list[FunctionalProbe]:
    """Every probe for one model. `holes` are (id, hole) pairs; only round through-holes get a screw probe."""
    screw_holes = [
        (hid, h)
        for hid, h in holes
        if h.through and h.coverage_deg >= ROUND_COVERAGE_DEG and h.diameter_mm <= SCREW_HOLE_MAX_MM
    ]
    out = [screw_probe(hid, h.diameter_mm) for hid, h in sorted(screw_holes, key=lambda x: x[0])]
    out += [interface_probe(i) for i in interfaces]
    out += printability_probes(min_wall_mm, overhang_mm2, area_mm2, orientation)
    return out


def as_part_tests(probes: Sequence[FunctionalProbe]) -> list[PartTest]:
    """Probes as P1 part tests (reported with ticks; never part of the pass rule)."""
    return [
        PartTest(
            id=p.id,
            description=p.text,
            value=p.value_mm,
            expected=p.expected_mm,
            tol=None,
            passed=p.passed,
            priority="P1",
        )
        for p in probes
    ]
