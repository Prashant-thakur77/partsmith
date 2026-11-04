"""Exit gate: verifier self-consistency on every family template.

For each template: build it at its defaults, make SYNTHETIC top-view measurements from its own rendered silhouette
(placed at a rotated, shifted pose), and verify the same model against them -> Hausdorff must be < 0.15 mm. Then
perturb the template's length parameter (MEASURE_MAP["length"]) by +1 mm and -1 mm: the "length" residual must have the
same sign as the perturbation. Prints a table; exit code 0 when every row passes.

    uv run python -m services.verifier.selfcheck
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

from services.agent.templates import Template, list_templates
from services.geom_worker.sandbox import WarmPool, run_program
from services.verifier.align import Rigid2D
from services.verifier.synthetic import synthetic_top_measurement
from services.verifier.verify import VerifyOutput, verify

SELF_HAUSDORFF_MAX_MM = 0.15
PERTURB_MM = 1.0
POSE = Rigid2D(17.0, 1.3, -0.7, False)


@dataclass
class Row:
    template: str
    length_param: str
    self_iou: float
    self_hausdorff_mm: float
    self_verified: bool
    plus_delta_mm: float | None
    minus_delta_mm: float | None
    plus_hausdorff_mm: float
    minus_hausdorff_mm: float
    perturbed_verified: bool
    ms: int

    @property
    def passed(self) -> bool:
        return (
            self.self_hausdorff_mm < SELF_HAUSDORFF_MAX_MM
            and self.plus_delta_mm is not None
            and self.minus_delta_mm is not None
            and self.plus_delta_mm > 0
            and self.minus_delta_mm < 0
        )


def _length_delta(out: VerifyOutput) -> float | None:
    for r in out.verification.residuals:
        if r.feature_id == "outline" and r.quantity == "length":
            return float(r.delta_mm)
    return None


def check_template(t: Template, pool: WarmPool | None = None, px_per_mm: float = 20.0) -> Row:
    t0 = time.perf_counter()
    base = run_program(t.code, t.defaults, outputs=(), pool=pool)
    if not base.ok:
        raise RuntimeError(f"{t.name} failed at defaults: {base.error.short() if base.error else '?'}")
    meas, photo = synthetic_top_measurement(base, pose=POSE, px_per_mm=px_per_mm)
    measurements = {"top": meas}
    masks = {"top": photo}
    own = verify(base, measurements, None, photo_masks=masks, px_per_mm=px_per_mm)
    lp = t.measure_map["length"]
    spec = t.param(lp)
    outs: dict[float, VerifyOutput] = {}
    for sign in (+1.0, -1.0):
        params = dict(t.defaults)
        params[lp] = spec.default + sign * PERTURB_MM
        if not spec.min <= params[lp] <= spec.max:
            raise RuntimeError(f"{t.name}: {lp} +/- {PERTURB_MM} mm leaves its range")
        r = run_program(t.code, params, outputs=(), pool=pool)
        outs[sign] = verify(r, measurements, None, photo_masks=masks, px_per_mm=px_per_mm)
        r.cleanup()
    base.cleanup()
    ov = own.verification
    return Row(
        template=t.name,
        length_param=lp,
        self_iou=ov.views[0].iou,
        self_hausdorff_mm=ov.views[0].hausdorff_mm,
        self_verified=ov.verified,
        plus_delta_mm=_length_delta(outs[1.0]),
        minus_delta_mm=_length_delta(outs[-1.0]),
        plus_hausdorff_mm=outs[1.0].verification.views[0].hausdorff_mm,
        minus_hausdorff_mm=outs[-1.0].verification.views[0].hausdorff_mm,
        perturbed_verified=outs[1.0].verification.verified or outs[-1.0].verification.verified,
        ms=int((time.perf_counter() - t0) * 1000),
    )


def run(pool: WarmPool | None = None) -> list[Row]:
    return [check_template(t, pool) for t in list_templates()]


def format_table(rows: list[Row]) -> str:
    head = (
        f"{'template':15s} {'length param':13s} {'self IoU':>8s} {'self HD':>8s} {'self ok':>7s} "
        f"{'+1 dL':>7s} {'-1 dL':>7s} {'+1 HD':>6s} {'-1 HD':>6s} {'pert. verified':>14s} {'gate':>5s} {'ms':>6s}"
    )
    lines = [head, "-" * len(head)]
    for r in rows:
        pd = f"{r.plus_delta_mm:+.3f}" if r.plus_delta_mm is not None else "n/a"
        md = f"{r.minus_delta_mm:+.3f}" if r.minus_delta_mm is not None else "n/a"
        lines.append(
            f"{r.template:15s} {r.length_param:13s} {r.self_iou:8.4f} {r.self_hausdorff_mm:8.3f} "
            f"{r.self_verified!s:>7s} {pd:>7s} {md:>7s} {r.plus_hausdorff_mm:6.2f} {r.minus_hausdorff_mm:6.2f} "
            f"{r.perturbed_verified!s:>14s} {'PASS' if r.passed else 'FAIL':>5s} {r.ms:6d}"
        )
    n_ok = sum(r.passed for r in rows)
    lines.append(f"{n_ok}/{len(rows)} templates pass (self Hausdorff < {SELF_HAUSDORFF_MAX_MM} mm and the length "
                 f"residual has the sign of a +/-{PERTURB_MM:g} mm perturbation). Measurements are SYNTHETIC.")  # fmt: skip
    return "\n".join(lines)


def main() -> int:
    pool = WarmPool(size=1)
    try:
        rows = run(pool)
    finally:
        pool.close()
    print(format_table(rows))
    return 0 if all(r.passed for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
