"""Fits where it goes: the measured mate (from the mating photo) against the model's matching feature, by code.

Informational only (P1 part tests): `verified` stays a statement about matching the broken part. Each mate is paired
with one feature of the executed CAD solid, measured on the solid (B-rep features and ray casts, as the functional
probes do), never with a number a model wrote:

- shaft or pin (``mate_peg``) → a bore the part goes onto: a declared interface (``interfaces(p)``) whose mate is a
  shaft, axle, pin or cable, else any declared interface, else the model hole closest in size;
- socket (``mate_hole``) → the part's outer size going into it: the narrowest outer width across the footprint;
- slot opening (``mate_slot``, the mat shows through) → the tab going into it: the model's plate thickness;
- panel edge (``mate_slot``, material) → the gap that holds it: a declared interface whose mate is a panel (else any
  declared interface).

The diametral clearance c = (what receives) − (what goes in) is classified with the functional probes' classes
(does not fit / press / sliding / loose / very loose), at c and at c ± σ (σ of the measured mate; the CAD side is
exact). "After printing on <preset>": internal fits (a hole or gap in the model) print about the preset's clearance
small on FDM (its documented delta, or the clearance this device's coupon reports taught), outer sizes print as
modelled; with the preset applied at export, internal fit knobs are opened by that clearance and print back to the
modelled size.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from partsmith_schemas.measurement import MateMeasurement
from partsmith_schemas.verification import FitClass, MateFit, PartTest, PrintedFit

from services.verifier.functional import fit_class

TEST_PREFIX = "fit.mate."
PEG_LABELS = ("shaft", "axle", "pin", "cable", "rod", "screw", "bolt", "wire")
PANEL_LABELS = ("panel", "sheet", "board", "edge", "rail", "strip", "door", "shelf")
MIN_HOLE_COVERAGE_DEG = 180.0  # a model hole must wrap at least this far round to hold a shaft
KIND_WORDS = {"mate_hole": "socket", "mate_peg": "shaft", "mate_slot": "slot"}

Source = Literal["interface", "nearest_hole", "outer_size", "plate_thickness", "none"]


@dataclass(frozen=True)
class PrinterFit:
    """The clearance a printer + material preset takes off internal fits, and where that number came from."""

    preset: str
    title: str
    clearance_mm: float
    source: Literal["learned", "preset"]
    label: str = ""


@dataclass(frozen=True)
class ModelSide:
    feature: str
    source: Source
    note: str
    size_mm: float
    internal: bool  # a hole or gap in the model (receives the mate) rather than an outer size (goes into it)


def _fc(c: float) -> FitClass:
    return fit_class(c)  # type: ignore[return-value]


def _interfaces(feats: Mapping[str, Any], labels: Sequence[str]) -> list[dict[str, Any]]:
    out = [dict(i) for i in feats.get("interfaces") or [] if i.get("gap_mm") is not None]
    match = [i for i in out if any(k in str(i.get("mate_label", "")).lower() for k in labels)]
    return match or out


def model_side(mate: MateMeasurement, feats: Mapping[str, Any]) -> ModelSide | None:
    """The model feature that meets this mate, measured on the solid (`feats`: the sandbox's `features` record)."""
    if mate.size is None:
        return None
    size = mate.size.value
    kind = mate.kind
    if kind == "mate_peg" or (kind == "mate_slot" and mate.material == "material"):
        labels = PEG_LABELS if kind == "mate_peg" else PANEL_LABELS
        itfs = _interfaces(feats, labels)
        if itfs:
            i = min(itfs, key=lambda x: abs(float(x["gap_mm"]) - size))
            how = "declared by the part program's interfaces(), measured on the solid by ray casts"
            return ModelSide(f"{i.get('label') or i.get('id')} (interface {i.get('id')})", "interface", how,
                             float(i["gap_mm"]), True)  # fmt: skip
        if kind == "mate_peg":
            holes = [h for h in feats.get("holes") or [] if float(h.get("coverage_deg", 0.0)) >= MIN_HOLE_COVERAGE_DEG]
            if holes:
                h = min(holes, key=lambda x: abs(float(x["diameter_mm"]) - size))
                return ModelSide(
                    f"hole at ({float(h['center_mm'][0]):.1f}, {float(h['center_mm'][1]):.1f}) mm",
                    "nearest_hole",
                    "no interface declared: the model hole closest in size to the shaft (B-rep cylinder)",
                    float(h["diameter_mm"]),
                    True,
                )
        return None
    b = feats.get("bbox_mm")
    if not b or len(b) != 6:
        return None
    sx, sy, sz = float(b[3]) - float(b[0]), float(b[4]) - float(b[1]), float(b[5]) - float(b[2])
    if kind == "mate_hole":
        return ModelSide("outer width across the footprint", "outer_size",
                         "the narrowest outer width of the model's footprint (bounding box): what goes into the socket",
                         min(sx, sy), False)  # fmt: skip
    plate = feats.get("plate_thickness_mm")
    t = float(plate) if plate else sz
    return ModelSide(
        "plate thickness" if plate else "model height",
        "plate_thickness",
        "the model's most common material thickness (ray casts): the tab that goes into the slot"
        if plate
        else "the model's height (no plate thickness found): what goes into the slot",
        t,
        False,
    )


def _range(c: float, sig: float) -> tuple[FitClass, FitClass]:
    return _fc(c - sig), _fc(c + sig)


def printed_fit(c: float, side: ModelSide, printer: PrinterFit, has_fit_knobs: bool) -> PrintedFit:
    """The fit after printing on `printer` (see the module docstring)."""
    d = printer.clearance_mm
    src = "learned from this device's coupon reports" if printer.source == "learned" else "documented starting point"
    if side.internal:
        cp = c - d
        with_c = c if has_fit_knobs else None
        text = (f"after printing on {printer.title}: {cp:.2f} mm, {_fc(cp)} (internal fits print about {d:.2f} mm "
                f"small: {printer.label or src})")  # fmt: skip
        if with_c is not None:
            text += f"; with that preset applied at export: {with_c:.2f} mm, {_fc(with_c)}"
        return PrintedFit(preset=printer.preset, title=printer.title, clearance_in_effect_mm=round(d, 3),
                          clearance_source=printer.source, clearance_label=printer.label or src, internal=True,
                          clearance_mm=round(cp, 3), fit=_fc(cp),
                          with_preset_clearance_mm=None if with_c is None else round(with_c, 3),
                          with_preset_fit=None if with_c is None else _fc(with_c), text=text)  # fmt: skip
    text = (f"after printing on {printer.title}: {c:.2f} mm, {_fc(c)} (outer sizes print as modelled; the preset "
            f"changes only internal fits)")  # fmt: skip
    return PrintedFit(preset=printer.preset, title=printer.title, clearance_in_effect_mm=round(d, 3),
                      clearance_source=printer.source, clearance_label=printer.label or src, internal=False,
                      clearance_mm=round(c, 3), fit=_fc(c), text=text)  # fmt: skip


def check_fit(
    mate: MateMeasurement,
    feats: Mapping[str, Any] | None,
    printer: PrinterFit | None = None,
    *,
    has_fit_knobs: bool = False,
) -> MateFit:
    word = KIND_WORDS[mate.kind] if mate.material != "material" or mate.kind != "mate_slot" else "panel edge"
    if not mate.ok or mate.size is None:
        why = mate.reason or "not measured"
        return MateFit(mate_id=mate.id, mate_kind=mate.kind, text=f"the {word} could not be measured: {why}")
    m, sig = mate.size.value, mate.size.sigma_mm
    side = model_side(mate, feats or {})
    sym = "Ø" if mate.shape == "round" or mate.kind == "mate_peg" else ""
    meas = f"the measured {word} {sym}{m:.2f} ± {sig:.2f} mm"
    if side is None:
        what = {"mate_peg": "bore or interface", "mate_slot": "gap or interface"}.get(mate.kind, "matching feature")
        return MateFit(mate_id=mate.id, mate_kind=mate.kind, mate_mm=m, mate_sigma_mm=sig,
                       text=f"{meas}: the model has no {what} to fit it")  # fmt: skip
    c = side.size_mm - m if side.internal else m - side.size_mm
    lo, hi = _range(c, sig)
    cls = _fc(c)
    if side.internal:
        rel = f"in the model's {side.feature} ({side.size_mm:.2f} mm)"
    else:
        rel = f"around the model's {side.feature} ({side.size_mm:.2f} mm)"
    if c < 0:
        text = f"does not fit: {meas} is {-c:.2f} mm too big for the model's {side.feature} ({side.size_mm:.2f} mm)" \
            if side.internal else \
            f"does not fit: {meas} is {-c:.2f} mm too small for the model's {side.feature} ({side.size_mm:.2f} mm)"  # fmt: skip
    else:
        text = f"{cls}: {meas} {rel}, {c:.2f} mm clearance"
    if lo != hi:
        text += f" (within ±σ: {lo} to {hi})"
    pf = printed_fit(c, side, printer, has_fit_knobs) if printer is not None else None
    return MateFit(
        mate_id=mate.id,
        mate_kind=mate.kind,
        model_feature=side.feature,
        model_feature_source=side.source,
        model_feature_note=side.note,
        model_mm=round(side.size_mm, 3),
        mate_mm=m,
        mate_sigma_mm=sig,
        clearance_mm=round(c, 3),
        clearance_sigma_mm=round(sig, 3),
        fit=cls,
        fit_low=lo,
        fit_high=hi,
        passed=c >= 0,
        printed=pf,
        text=text,
    )


def check_fits(
    mates: Sequence[MateMeasurement],
    feats: Mapping[str, Any] | None,
    printer: PrinterFit | None = None,
    *,
    has_fit_knobs: bool = False,
) -> list[MateFit]:
    return [check_fit(m, feats, printer, has_fit_knobs=has_fit_knobs) for m in mates]


def reprint(fits: Sequence[MateFit], printer: PrinterFit, has_fit_knobs: bool) -> list[MateFit]:
    """The same fits with the printer note recomputed for another preset or a learned clearance (the CAD and the
    measured mate are unchanged)."""
    out = []
    for f in fits:
        if f.clearance_mm is None or f.model_mm is None or f.printed is None:
            out.append(f)
            continue
        side = ModelSide(f.model_feature, f.model_feature_source, f.model_feature_note, f.model_mm, f.printed.internal)
        out.append(f.model_copy(update={"printed": printed_fit(f.clearance_mm, side, printer, has_fit_knobs)}))
    return out


def as_part_tests(fits: Sequence[MateFit]) -> list[PartTest]:
    """P1 tests "fits where it goes" (never part of the pass rule). value = clearance, expected = 0 (it must not be
    negative)."""
    out = []
    for f in fits:
        desc = "fits where it goes: " + f.text
        if f.printed is not None:
            desc += "; " + f.printed.text
        out.append(PartTest(id=f"{TEST_PREFIX}{f.mate_id}", description=desc, value=f.clearance_mm,
                            expected=0.0 if f.clearance_mm is not None else None, tol=None, passed=f.passed,
                            priority="P1"))  # fmt: skip
    return out


def reason_line(fits: Sequence[MateFit]) -> str | None:
    """One plain-words line for `Verification.reasons`."""
    if not fits:
        return None
    parts = [f"{f.mate_id}: {f.text}" for f in fits]
    bad = any(f.clearance_mm is not None and not f.passed for f in fits)
    head = "Does not fit where it goes" if bad else "Fits where it goes"
    return f"{head} (mating photo; informational, it does not change verified): " + "; ".join(parts)


def does_not_fit(tests: Sequence[PartTest]) -> list[PartTest]:
    """The "fits where it goes" tests that say it does not fit (for the export gate's warning)."""
    return [t for t in tests if t.id.startswith(TEST_PREFIX) and not t.passed and t.value is not None]
