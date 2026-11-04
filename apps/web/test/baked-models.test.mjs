// The baked model index and mesh files the hero and pages read: real files from public/deck/models.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { BakedIndexSchema, decodeMesh, defaultStepIndex, largestSizeMm, meshUrl } from "../src/lib/baked-models.ts";

const raw = JSON.parse(readFileSync(new URL("../public/deck/models/index.json", import.meta.url), "utf8"));
const index = BakedIndexSchema.parse(raw);
const knob = index.parts["battery-cover-45mm"].knobs.length;

test("the hero's part and knob exist, with several real steps of different sizes", () => {
  assert.ok(knob.steps.length >= 3);
  assert.equal(new Set(knob.steps.map((s) => s.size_mm[0])).size, knob.steps.length);
});

test("the slider starts at the step nearest the knob's default", () => {
  assert.equal(knob.steps[defaultStepIndex(knob)].value, knob.default);
});

test("the fixed camera frames the largest step", () => {
  assert.equal(largestSizeMm(knob), Math.max(...knob.steps.map((s) => s.size_mm[0])));
});

test("every step's mesh file decodes, and its size matches the index", () => {
  for (const step of knob.steps) {
    const file = readFileSync(new URL(`../public/deck/${step.file}`, import.meta.url));
    const buf = file.buffer.slice(file.byteOffset, file.byteOffset + file.byteLength);
    const { positions, indices } = decodeMesh(buf);
    assert.equal(indices.length / 3, step.triangles);
    let lo = Infinity;
    let hi = -Infinity;
    for (let i = 0; i < positions.length; i += 3) {
      lo = Math.min(lo, positions[i]);
      hi = Math.max(hi, positions[i]);
    }
    assert.ok(Math.abs(hi - lo - step.size_mm[0]) < 0.01, `${step.file}: ${hi - lo} vs ${step.size_mm[0]}`);
  }
});

test("a truncated mesh file is refused rather than drawn wrong", () => {
  const u = new Uint32Array([100, 100]);
  assert.throws(() => decodeMesh(u.buffer), /truncated/);
  assert.throws(() => decodeMesh(new ArrayBuffer(4)), /too short/);
});

test("mesh paths resolve under the deck", () => {
  assert.equal(meshUrl("models/a.bin"), "/deck/models/a.bin");
});
