// Unit tests for the playground / describe helpers (node --test; no browser, no network).
import assert from "node:assert/strict";
import test from "node:test";
import { DescribeRecordSchema, TemplateCardSchema } from "../src/lib/api-types.ts";
import { activePreset, applyPreset, changedValues, minutesText, parseAnswers, playgroundQuery, programLines, snapValue, valueTag, valuesFromQuery } from "../src/lib/playground.ts";

const spec = (name, d, min, max, step, extra = {}) => ({ name, default: d, min, max, step, unit: "mm", affects_fit: true, label: name, topology: false, ...extra });
const PARAMS = [spec("length", 40, 24, 100, 0.1), spec("hole_d", 3.5, 2, 6, 0.05), spec("hole_count", 2, 0, 2, 1, { unit: "", topology: true })];

test("query values are clamped, snapped and limited to real knobs", () => {
  const v = valuesFromQuery(PARAMS, new URLSearchParams("length=500&hole_d=3.41&hole_count=1.6&colour=3&t=cable_clip"));
  assert.deepEqual(v, { length: 100, hole_d: 3.4, hole_count: 2 });
  assert.deepEqual(valuesFromQuery(PARAMS, { length: "abc", hole_d: "" }), { length: 40, hole_d: 3.5, hole_count: 2 });
  assert.equal(snapValue(PARAMS[0], 41.234), 41.2);
});

test("shareable query holds the template and only the changed knobs, sorted", () => {
  const q = playgroundQuery("cable_clip", PARAMS, { length: 45, hole_d: 3.5, hole_count: 1 });
  assert.equal(q, "t=cable_clip&hole_count=1&length=45");
  assert.deepEqual(changedValues(PARAMS, { length: 40.04, hole_d: 3.5, hole_count: 2 }), {});
});

test("presets apply on top of the defaults and are recognised while untouched", () => {
  const presets = [{ id: "m3", values: { hole_d: 3.4 } }, { id: "one", values: { hole_count: 1 } }];
  const v = applyPreset(PARAMS, presets[0]);
  assert.deepEqual(v, { length: 40, hole_d: 3.4, hole_count: 2 });
  assert.equal(activePreset(PARAMS, v, presets)?.id, "m3");
  assert.equal(activePreset(PARAMS, { ...v, length: 41 }, presets), null);
});

test("the program shows the current values in PARAMS and marks what changed", () => {
  const code = 'import cadquery as cq\n\nPARAMS = {  # name: (...)\n    "length": (40.0, 24.0, 100.0, 0.1, "mm", True, "Base length"),\n    "hole_count": (2, 0, 2, 1, "", False, "Screw holes"),\n}\n\ndef build(p):\n    "length": (1.0, 2)\n';
  const lines = programLines(code, { length: 45.5, hole_count: 2 });
  const l = lines.find((x) => x.knob === "length");
  assert.equal(l.text, '    "length": (45.5, 24.0, 100.0, 0.1, "mm", True, "Base length"),');
  assert.equal(l.changed, true);
  assert.equal(lines.find((x) => x.knob === "hole_count").changed, false);
  assert.equal(lines.at(-1).knob, null, "only lines inside PARAMS are knobs");
  assert.equal(lines.length, code.split("\n").length);
});

test("value tags follow the source until the knob moves", () => {
  assert.equal(valueTag({ source: "user", value: 6 }, 6, 0.05), "you said");
  assert.equal(valueTag({ source: "answer", value: 50 }, 50, 0.1), "you answered");
  assert.equal(valueTag({ source: "default", value: 2 }, undefined, 1), "default");
  assert.equal(valueTag({ source: "user", value: 6 }, 7, 0.05), "changed");
});

test("answers: empty means default, junk is reported, mm and commas are fine", () => {
  assert.deepEqual(parseAnswers({ length: "45 mm", hole_d: "", width: "3,5" }), { answers: { length: 45, hole_d: null, width: 3.5 }, bad: [] });
  assert.deepEqual(parseAnswers({ length: "long" }).bad, ["length"]);
  assert.equal(minutesText(5.6), "6 min");
  assert.equal(minutesText(65), "1 h 05 min");
});

test("schemas accept the backend's describe record and template card", () => {
  const card = TemplateCardSchema.parse({ name: "spacer", family: "spacer", title: "Spacer", params: PARAMS, defaults: { length: 40 }, thumbnail_url: "/a.png", thumbnail_2x_url: "/b.png" });
  assert.deepEqual(card.presets, []);
  const rec = DescribeRecordSchema.parse({
    id: "d_261031_0123abcd", text: "a spacer", status: "no_fit", created_at: 1, template: null,
    no_fit: { reason: "none fits", next: [{ href: "/fix", label: "Photograph it" }] },
  });
  assert.equal(rec.no_fit.next[0].href, "/fix");
  assert.equal(rec.checks, undefined);
});
