// Stretch against knob, on the real baked example: numbers must come out of the bakes and the mesh arithmetic.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { BakedIndexSchema } from "../src/lib/baked-models.ts";
import { baseIndex, compareRows, meshScale } from "../src/lib/stretch.ts";

const { star } = BakedIndexSchema.parse(JSON.parse(readFileSync(new URL("../public/deck/models/index.json", import.meta.url), "utf8")));

test("the sliders start at the part's own size", () => {
  assert.equal(star.knobs.length[baseIndex(star, "length")].value, star.base.size_mm[0]);
  assert.ok(Math.abs(star.knobs.hole_d[baseIndex(star, "hole_d")].value - star.base.holes[0].d) < 0.01);
});

test("at the base size, both sides agree and nothing has moved", () => {
  const step = star.knobs.hole_d[baseIndex(star, "hole_d")];
  assert.deepEqual(meshScale(star, "hole_d", step), [1, 1, 1]);
  const shift = compareRows(star, "hole_d", step).find((r) => r.what === "Hole spacing shift");
  assert.equal(shift.mesh, "0.00 mm");
  assert.equal(shift.knob, "0.00 mm");
});

test("a bigger hole by scaling moves the holes apart and grows the plate; the knob does neither", () => {
  const step = star.knobs.hole_d[star.knobs.hole_d.length - 2];
  const rows = compareRows(star, "hole_d", step);
  const shift = rows.find((r) => r.what === "Hole spacing shift");
  assert.ok(parseFloat(shift.mesh) > 1);
  assert.ok(parseFloat(shift.knob) < 0.01);
  const plate = rows.find((r) => r.what === "Plate length");
  assert.ok(parseFloat(plate.mesh) > star.base.size_mm[0]);
  assert.equal(parseFloat(plate.knob), star.base.size_mm[0]);
});

test("a longer plate by scaling makes oval holes; the knob keeps them round", () => {
  const step = star.knobs.length[star.knobs.length.length - 1];
  assert.equal(meshScale(star, "length", step)[1], 1);
  const shape = compareRows(star, "length", step).find((r) => r.what === "Hole shape");
  assert.match(shape.mesh, /^oval/);
  assert.equal(shape.knob, "round");
});
