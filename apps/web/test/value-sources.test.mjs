// Unit tests for "where each value came from": source kinds, legend styles (contrast, non-colour cues) and the value
// list built from a job detail (node --test; no browser, no network). Reads committed replays.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { EventSchema, MeasurementsSchema, PartSpecSchema, VerificationSchema } from "../src/lib/api-types.ts";
import {
  SOURCE_KINDS,
  SOURCE_STYLES,
  checkText,
  contrastRatio,
  kindCounts,
  sourceKind,
  swatchCss,
  valueItems,
  valueText,
} from "../src/lib/value-sources.ts";

const REPLAYS = new URL("../../../data/replays/", import.meta.url);
// replays are found by their demo sample (data/replays/seed_index.json), so a re-seed with new job ids keeps working
const SEED_INDEX = JSON.parse(readFileSync(new URL("seed_index.json", REPLAYS), "utf8"));
const replayOf = (sample) => SEED_INDEX[sample];
const json = (id, f) => JSON.parse(readFileSync(new URL(`${id}/${f}`, REPLAYS), "utf8"));

function replayInput(id) {
  const measurements = Object.fromEntries(Object.entries(json(id, "measurements.json")).map(([k, v]) => [k, MeasurementsSchema.parse(v)]));
  const artifacts = readFileSync(new URL(`${id}/run.jsonl`, REPLAYS), "utf8")
    .split("\n")
    .filter(Boolean)
    .map((l) => EventSchema.parse(JSON.parse(l)))
    .filter((e) => e.t === "artifact");
  return { partspec: PartSpecSchema.parse(json(id, "partspec.json")), measurements, verification: VerificationSchema.parse(json(id, "verification.json")), artifacts };
}

// Relative luminance of the neutral surfaces in styles/globals.css (oklch L with no chroma: Y = L³).
const LIGHT_BG = { surface: 1, surface2: 0.967 ** 3, viewer: 0.965 ** 3 };
const DARK_BG = { surface: 0.18 ** 3, surface2: 0.205 ** 3, viewer: 0.17 ** 3 };

test("every source colour is text-safe (WCAG AA 4.5:1) on the light and dark surfaces", () => {
  for (const k of SOURCE_KINDS) {
    const s = SOURCE_STYLES[k];
    for (const [name, y] of Object.entries(LIGHT_BG)) assert.ok(contrastRatio(s.light, y) >= 4.5, `${k} light on ${name}: ${contrastRatio(s.light, y).toFixed(2)}`);
    for (const [name, y] of Object.entries(DARK_BG)) assert.ok(contrastRatio(s.dark, y) >= 4.5, `${k} dark on ${name}: ${contrastRatio(s.dark, y).toFixed(2)}`);
  }
});

test("no source is told apart by colour alone: labels, icons and swatch patterns are all distinct", () => {
  const distinct = (f) => new Set(SOURCE_KINDS.map((k) => f(SOURCE_STYLES[k]))).size === SOURCE_KINDS.length;
  assert.ok(distinct((s) => s.label));
  assert.ok(distinct((s) => s.icon));
  assert.ok(distinct((s) => s.pattern));
  for (const k of SOURCE_KINDS) assert.ok(swatchCss(SOURCE_STYLES[k].pattern).border.includes("currentColor"));
});

test("source kinds follow the schema, refined only by the server's evidence", () => {
  assert.equal(sourceKind("measured", "see-through fit"), "measured");
  assert.equal(sourceKind("measured", "SAM point prompt; pointed by Spark (narration)"), "pointed");
  assert.equal(sourceKind("user_stated", null), "user_stated");
  assert.equal(sourceKind("cited"), "cited");
  assert.equal(sourceKind("inferred"), "inferred");
  assert.equal(sourceKind("something-new"), "measured");
  assert.equal(sourceKind(undefined), "measured");
});

test("the L-bracket replay lists measured, stated and inferred values, each traced to its evidence", () => {
  const items = valueItems(replayInput(replayOf("demo-l-bracket")));
  const by = Object.fromEntries(items.map((i) => [i.id, i]));
  assert.equal(by["dim.length"].kind, "measured");
  assert.deepEqual(by["dim.length"].anchor, { type: "dim", axis: "x" });
  assert.ok(by["dim.length"].boundMm, "the thick top view's range is carried through");
  assert.ok(by["dim.length"].evidence.some((e) => /^top: measured outline/.test(e.label)));
  assert.equal(by["dim.thickness"].kind, "user_stated");
  assert.equal(by["dim.thickness"].anchor, null, "a plate thickness is not drawn on the model's height");
  assert.deepEqual(by["dim.thickness"].evidence, []);
  assert.equal(by["dim.height"].kind, "measured");
  assert.equal(by["dim.height"].anchor.axis, "z");
  const hole = by["feature.hole_1.diameter"];
  assert.equal(hole.kind, "measured");
  assert.equal(hole.featureId, "hole_1");
  assert.deepEqual(hole.anchor, { type: "point", at: [-18.643, -3.221] });
  assert.ok(hole.residuals.length >= 1, "the verifier's hole residuals are attached");
  assert.match(checkText(hole), /^The verifier compared the model with it/);
  const knob = by["knob.bend_radius"];
  assert.equal(knob.kind, "inferred");
  assert.equal(knob.unchecked, true);
  assert.equal(knob.anchor, null);
  assert.equal(checkText(knob), "Not checked against a photo.");
  assert.deepEqual(kindCounts(items).map((c) => c.kind), ["measured", "user_stated", "inferred"]);
});

test("a broken part's rebuilt region is its own entry with the reconstruction artifacts as evidence", () => {
  const items = valueItems(replayInput(replayOf("demo-broken-latch-corner")));
  const region = items.find((i) => i.id === "region.broken");
  assert.ok(region);
  assert.equal(region.kind, "completed");
  assert.equal(region.anchor.type, "polygon");
  assert.match(region.note, /mirroring the intact side/);
  assert.ok(region.evidence.some((e) => /mirror completion/.test(e.label)));
  assert.ok(region.evidence.some((e) => /rejected by code gate/.test(e.label)));
  assert.match(checkText(region), /Left out of the comparison/);
});

test("stated, cited and narrated values pick their kinds; values print with sigma", () => {
  const measured = (source, note, extra = {}) => ({ value: 4.2, source, sigma_mm: 0.05, evidence: note ? { view: "top", note } : null, ...extra });
  const items = valueItems({
    partspec: {
      family: "knob",
      thickness: measured("user_stated", null),
      features: [
        { kind: "through_hole", id: "hole_1", center_mm: [1, 2], diameter: measured("measured", "pointed by Spark (narration)") },
        { kind: "d_shaft_bore", id: "bore", diameter: measured("cited", null, { evidence: { citation: { url: "https://example.com/spec", title: "spec", quote: "6 mm" } } }) },
      ],
      broken_region: null,
    },
    measurements: {},
    verification: null,
    artifacts: [{ t: "artifact", job: "j", seq: 1, ts: 0, ctx: "", kind: "narration", sha: "n", url: "/n.json", iter: null, label: "narration" }],
  });
  const by = Object.fromEntries(items.map((i) => [i.id, i]));
  assert.equal(by["feature.hole_1.diameter"].kind, "pointed");
  assert.ok(by["feature.hole_1.diameter"].evidence.some((e) => e.url === "/n.json"));
  assert.equal(by["feature.bore.diameter"].kind, "cited");
  assert.equal(by["feature.bore.diameter"].citation.url, "https://example.com/spec");
  assert.equal(by["feature.bore.diameter"].anchor, null, "no centre, no marker: side list only");
  assert.equal(valueText(by["feature.hole_1.diameter"]), "4.20 ± 0.05 mm");
  assert.equal(valueText({ value: null, unit: "mm", sigmaMm: null }), "—");
  assert.equal(checkText(by["feature.hole_1.diameter"]), "No feature test compared the model with this value.");
});
