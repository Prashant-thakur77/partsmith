/**
 * Stretch against knob: what happens to a holed plate when you get a new size by scaling its mesh, against turning the
 * program's knob. The knob side reads the sizes measured on each real bake; the mesh side is arithmetic on the base part.
 */
import type { BakedStar, BakedStep } from "./baked-models";

/** Pure and free of runtime imports so `node --test` can load it. */
const fmtNum = (v: number) => v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export type Goal = "hole_d" | "length";
export type CompareRow = { what: string; mesh: string; knob: string };

const spacing = (holes: { x: number }[] | undefined) => {
  if (!holes || holes.length < 2) return 0;
  return holes[holes.length - 1]!.x - holes[0]!.x;
};

/** The base value of the knob: where its slider starts, and the size the mesh is scaled from. */
export function baseIndex(star: BakedStar, goal: Goal): number {
  const steps = star.knobs[goal];
  const base = goal === "length" ? star.base.size_mm[0] : (star.base.holes[0]?.d ?? 0);
  let best = 0;
  steps.forEach((s, i) => {
    if (Math.abs(s.value - base) < Math.abs(steps[best]!.value - base)) best = i;
  });
  return best;
}

/** The axis scale that stretches the mesh to the target: uniform to grow a hole, along the plate to lengthen it. */
export function meshScale(star: BakedStar, goal: Goal, step: BakedStep): [number, number, number] {
  const base = star.knobs[goal][baseIndex(star, goal)]!.value;
  const k = step.value / base;
  return goal === "hole_d" ? [k, k, k] : [k, 1, 1];
}

export function compareRows(star: BakedStar, goal: Goal, step: BakedStep): CompareRow[] {
  const [k] = meshScale(star, goal, step);
  const s0 = spacing(star.base.holes);
  const sKnob = spacing(step.holes);
  const d0 = star.knobs.hole_d[baseIndex(star, "hole_d")]!.value;
  const L0 = star.base.size_mm[0];
  const dKnob = step.holes?.[0]?.d ?? d0;
  if (goal === "hole_d") {
    return [
      { what: "Hole diameter", mesh: `${fmtNum(d0 * k)} mm`, knob: `${fmtNum(dKnob)} mm` },
      { what: "Hole spacing shift", mesh: `${fmtNum(Math.abs(s0 * k - s0))} mm`, knob: `${fmtNum(Math.abs(sKnob - s0))} mm` },
      { what: "Plate length", mesh: `${fmtNum(L0 * k)} mm`, knob: `${fmtNum(step.size_mm[0])} mm` },
    ];
  }
  return [
    { what: "Plate length", mesh: `${fmtNum(L0 * k)} mm`, knob: `${fmtNum(step.size_mm[0])} mm` },
    { what: "Hole shape", mesh: Math.abs(k - 1) < 0.001 ? "round" : `oval, ${fmtNum(k)}:1`, knob: "round" },
    { what: "Hole size along the plate", mesh: `${fmtNum(d0 * k)} mm`, knob: `${fmtNum(dKnob)} mm` },
  ];
}
