/**
 * Material and load notes for parts that carry a load (hinge, bracket, latch, clip, hook): one rule table, keyed by
 * family. These are printing advice, not measurements and not a strength rating — every note ends with the same
 * warning that a printed part is not for safety-critical loads. Pure and free of runtime imports so `node --test` can
 * load it.
 */

export type LoadNote = {
  family: string;
  title: string;
  material: string;
  orientation: string;
  walls: string;
  warning: string;
};

export const SAFETY_WARNING = "Not for safety-critical loads: nothing that holds a person, a child, a vehicle part or weight overhead.";

const HEAT = "PETG or ASA rather than PLA: PLA creeps under a steady load and softens in a hot car, in the sun or near a heater.";

type Rule = Omit<LoadNote, "family" | "warning">;

export const LOAD_RULES: Record<string, Rule> = {
  hook: {
    title: "Carries a hanging load",
    material: HEAT,
    orientation: "Print it lying on its side, so the layers run around the curve of the hook instead of stacking across it — layers pull apart far more easily than they bend.",
    walls: "4 or more walls and 40 % or more infill; the walls carry most of the load.",
  },
  bracket: {
    title: "Carries a load at a corner",
    material: HEAT,
    orientation: "Print it on its side, so both arms and the corner lie in the layers; printed standing up, the corner splits along a layer line.",
    walls: "4 or more walls and 40 % or more infill; add a fillet at the inside corner if the knobs allow it.",
  },
  hinge: {
    title: "Turns and carries the door's weight",
    material: "PETG (tougher and slides better than PLA); ASA if it lives outdoors or in the sun.",
    orientation: "Print the leaf flat, so the knuckle's pin hole runs along the layers; check the pin hole with the fit-test coupon first.",
    walls: "3 to 4 walls and 30 % or more infill.",
  },
  latch: {
    title: "Flexes every time it closes",
    material: "PETG: it bends and springs back, where PLA tends to crack after many openings.",
    orientation: "Print it so the springy arm lies flat on the bed and bends along the layers, never across them.",
    walls: "3 or more walls; keep the arm solid (it is thin enough that walls fill it).",
  },
  clip: {
    title: "Snaps on and holds",
    material: "PETG: it flexes and springs back; PLA clips tend to crack at the root of the arm.",
    orientation: "Print it so the flexing arm lies flat on the bed and bends along the layers.",
    walls: "3 or more walls; thin arms print solid.",
  },
};

/** The note for a family, or null for parts that carry no real load (knobs, spacers, covers…). */
export function loadNote(family: string | null | undefined): LoadNote | null {
  if (!family) return null;
  const rule = LOAD_RULES[family];
  return rule ? { family, ...rule, warning: SAFETY_WARNING } : null;
}

/**
 * "Which way up" with one source of truth: when a print plan computed an orientation from the mesh, that is the
 * orientation (the slicer numbers next to it assume it) and the family's strength advice is stated as advice that
 * defers to it, so "mounting face on the bed" and "print it on its side" never read as two instructions. Without a
 * plan, the strength advice alone.
 */
export function orientationAdvice(note: Pick<LoadNote, "orientation">, planOrientation?: string | null): string {
  const computed = (planOrientation ?? "").replace(/^[+-][XYZ]:\s*/, "").trim();
  if (!computed) return note.orientation;
  const advice = note.orientation.charAt(0).toLowerCase() + note.orientation.slice(1);
  return `Computed print orientation: ${computed} (picked from the mesh for supports and overhangs). For strength, ${advice} If that is not the computed orientation, re-slice: the supports, time and grams shown assume the computed one.`;
}
