// Unit tests for the "fits where it goes" helpers and their tolerant schema (node --test; no browser, no network).
import assert from "node:assert/strict";
import test from "node:test";
import { MateFitResultSchema } from "../src/lib/api-types.ts";
import { MATE_TAP_KINDS, TOP_TAP_KINDS, clearanceText, fitRows, fitTone, fitWarning, mateWord, pointsPayload, sizeText } from "../src/lib/mate-fit.ts";

test("the points field carries top and mating taps, and nothing when nothing was tapped", () => {
  assert.equal(pointsPayload([], []), null);
  assert.equal(pointsPayload(null, undefined), null);
  assert.deepEqual(JSON.parse(pointsPayload([{ x: 1, y: 2, kind: "hole" }], [])), { top: [{ x: 1, y: 2, kind: "hole" }] });
  assert.deepEqual(JSON.parse(pointsPayload([], [{ x: 5, y: 6, kind: "mate_peg", extra: 1 }])), { mating: [{ x: 5, y: 6, kind: "mate_peg" }] });
  assert.ok(MATE_TAP_KINDS.includes("mate_slot") && MATE_TAP_KINDS.includes("exclude") && !MATE_TAP_KINDS.includes("hole"));
  assert.ok(!TOP_TAP_KINDS.includes("mate_hole"));
});

test("mates are named in words and sized with their sigma", () => {
  assert.equal(mateWord("mate_hole"), "socket");
  assert.equal(mateWord("mate_peg"), "shaft");
  assert.equal(mateWord("mate_slot", "opening"), "slot");
  assert.equal(mateWord("mate_slot", "material"), "panel edge");
  assert.equal(sizeText({ kind: "mate_peg", shape: "strip", size: { value: 5.999, sigma_mm: 0.007 } }), "Ø 6.00 ± 0.01 mm");
  assert.equal(sizeText({ kind: "mate_slot", shape: "strip", size: { value: 3.015, sigma_mm: 0.056 } }), "width 3.02 ± 0.06 mm");
  assert.equal(sizeText({ kind: "mate_hole", shape: "round", size: null }), null);
  assert.equal(clearanceText(0.2, 0.02), "0.20 ± 0.02 mm clearance");
  assert.equal(clearanceText(-0.12), "0.12 mm interference");
  assert.equal(clearanceText(null), null);
  assert.equal(fitTone("does not fit"), "bad");
  assert.equal(fitTone("sliding fit"), "ok");
  assert.equal(fitTone("press fit"), "warn");
  assert.equal(fitTone(null), "neutral");
});

const RECORD = {
  view: "mating",
  mates: [
    { id: "mate_1", kind: "mate_peg", ok: true, material: "material", shape: "strip", point_source: "user", method: "shaft on its side",
      size: { value: 6.0, sigma_mm: 0.01, source: "measured" } },
    { id: "mate_2", kind: "mate_hole", ok: false, reason: "the point is outside the photo" },
    { id: "bad" }, // malformed: dropped, never half-shown
  ],
  fits: [
    { mate_id: "mate_1", mate_kind: "mate_peg", model_feature: "shaft bore (interface shaft_bore)", model_feature_source: "interface",
      model_mm: 6.2, mate_mm: 6.0, mate_sigma_mm: 0.01, clearance_mm: 0.2, clearance_sigma_mm: 0.01, fit: "sliding fit",
      fit_low: "sliding fit", fit_high: "sliding fit", passed: true, text: "sliding fit: ...",
      printed: { preset: "pla-fdm-0.4", title: "PLA · FDM 0.4 mm nozzle", clearance_in_effect_mm: 0.2, clearance_source: "preset", internal: true,
        clearance_mm: 0.0, fit: "press fit", text: "after printing on PLA · FDM 0.4 mm nozzle: 0.00 mm, press fit" } },
    { mate_id: "mate_2", mate_kind: "mate_hole", passed: false, text: "the socket could not be measured", printed: { nonsense: true } },
  ],
  notes: ["MOCK: picked by code", 3],
};

test("the card rows come from the server's record only, malformed entries dropped", () => {
  const res = MateFitResultSchema.parse(RECORD);
  assert.equal(res.mates.length, 2);
  assert.deepEqual(res.notes, ["MOCK: picked by code"]);
  assert.equal(res.fits[1].printed, null);
  const [a, b] = fitRows(res);
  assert.equal(a.what, "shaft");
  assert.equal(a.measured, "Ø 6.00 ± 0.01 mm");
  assert.equal(a.pointedBy, "you tapped it");
  assert.equal(a.model, "shaft bore (interface shaft_bore): 6.20 mm");
  assert.equal(a.clearance, "0.20 ± 0.01 mm clearance");
  assert.equal(a.fit, "sliding fit");
  assert.equal(a.tone, "ok");
  assert.equal(a.range, null);
  assert.match(a.printer, /after printing on PLA/);
  assert.equal(a.problem, null);
  assert.equal(b.measured, null);
  assert.equal(b.problem, "the point is outside the photo");
  assert.deepEqual(fitRows(null), []);
});

test("the export menu warns only when a fit test says it does not fit", () => {
  const tests = [
    { id: "probe.overhang", passed: false, value: null, description: "needs supports" },
    { id: "fit.mate.mate_1", passed: false, value: -0.12,
      description: "fits where it goes: does not fit: the measured shaft Ø6.32 ± 0.02 mm is 0.12 mm too big for the model's shaft bore (6.20 mm); after printing on PLA" },
  ];
  assert.equal(fitWarning({ tests }), "Does not fit where it goes: the measured shaft Ø6.32 ± 0.02 mm is 0.12 mm too big for the model's shaft bore (6.20 mm).");
  assert.equal(fitWarning({ tests: [{ ...tests[1], passed: true }] }), null);
  assert.equal(fitWarning({ tests: [{ ...tests[1], value: null }] }), null); // not measured is not "does not fit"
  assert.equal(fitWarning(null), null);
});
