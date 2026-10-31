// Unit tests for the verdict explanations (node --test; no browser, no network). Numbers are copied from records the
// preview API served: the caster wheel part, the wall-hook job and the verified spacer job.
import assert from "node:assert/strict";
import test from "node:test";
import { boxVsPhotoNote, installPanel, installStepsNote, nearLimitNote, statedThicknessNote, verdictBreakdown } from "../src/lib/verdict-notes.ts";

const P0 = (id, passed = true) => ({ id, description: `${id} test`, value: 1, expected: 1, tol: 0.3, passed, priority: "P0" });

// caster-wheel-62mm: every part test passes, the side view's outline gap is over the limit
const caster = {
  verified: false,
  status: "best_effort",
  thresholds: { hausdorff_mm: 0.5, iou: 0.97 },
  reasons: [
    "top view (photo frame): IoU 0.991 (needs >= 0.97), Hausdorff 0.24 mm (needs <= 0.5 mm)",
    "side view (photo frame): IoU 0.981 (not gated), mean contour distance 0.14 mm (needs <= 0.15 mm), Hausdorff 0.63 mm (needs <= 0.5 mm) (worst at x=-1.2, y=-8.3 mm) - fails",
  ],
  views: [
    { view: "top", iou: 0.9913, hausdorff_mm: 0.2401, mean_mm: 0.066 },
    { view: "side", iou: 0.981, hausdorff_mm: 0.6333, mean_mm: 0.1398 },
  ],
  tests: [...Array.from({ length: 15 }, (_, i) => P0(`t${i}`)), { ...P0("adv"), priority: "P1" }],
  vetoes: [],
  max_error_mm: 0.6333,
};

test("a best-effort part whose tests all pass says which check failed and that it decided the status", () => {
  const b = verdictBreakdown(caster);
  assert.equal(b.decided, "Best effort because of the side view: verified needs every required test and every view to pass.");
  assert.ok(b.passed.includes("all 15 required part tests"));
  assert.ok(b.passed.includes("top view outline gap 0.24 mm ≤ 0.50 mm"));
  assert.ok(b.passed.includes("top view overlap 0.991 ≥ 0.97"));
  assert.ok(b.passed.includes("side view average edge gap 0.14 mm ≤ 0.15 mm"));
  assert.deepEqual(b.failed, ["side view outline gap 0.63 mm > 0.50 mm"]);
  assert.deepEqual(b.notGated, ["side view overlap 0.981 is reported but not gated (small silhouette)"]);
});

test("failing required tests and a blocking veto are named as causes; a verified record says so", () => {
  const b = verdictBreakdown({ ...caster, views: [caster.views[0]], reasons: [caster.reasons[0]], tests: [P0("a"), P0("b", false)], vetoes: [{ feature: "hinge_knuckles", issue: "missing", severity: "blocking" }] });
  assert.match(b.decided, /^Best effort because of 1 required test and the judge's blocking veto:/);
  assert.ok(b.failed.includes("blocking judge veto on hinge knuckles"));
  assert.ok(b.failed.some((f) => f.startsWith("required test: b test")));
  const ok = verdictBreakdown({ ...caster, verified: true, status: "verified", views: [caster.views[0]], reasons: [caster.reasons[0]] });
  assert.equal(ok.decided, "Verified: every required test and every view passed.");
  assert.equal(ok.failed.length, 0);
  assert.equal(verdictBreakdown(null), null);
});

test("a verified result within 0.01 mm of the limit asks for the fit-test coupon first", () => {
  const v = (max, verified = true) => ({ verified, max_error_mm: max, thresholds: { hausdorff_mm: 0.5, iou: 0.97 } });
  assert.equal(nearLimitNote(v(0.49)), "Near the limit (0.49 mm of 0.50 mm): print the fit-test coupon first.");
  assert.match(nearLimitNote(v(0.4999)), /^Near the limit \(0\.50 mm of 0\.50 mm\)/);
  assert.equal(nearLimitNote(v(0.48)), null);
  assert.equal(nearLimitNote(v(0.495, false)), null); // not verified: the best-effort notice already covers it
  assert.equal(nearLimitNote(null), null);
});

test("the 3D box and the photo's length are named as different measurements when they differ", () => {
  // wall hook j_261029_5e9d54d1: box 44.8 × 20.1 × 40.5 mm, length test 49.81 vs 49.83 (passed)
  const hook = { validity: { bbox_mm: [44.8, 20.1, 40.5] }, tests: [{ id: "bbox.x", description: "length", value: 49.809, expected: 49.829, tol: 0.3, passed: true, priority: "P0" }] };
  const note = boxVsPhotoNote(hook);
  assert.match(note, /^The size on the 3D view \(44\.8 × 20\.1 × 40\.5 mm\) is the model's box in its own X, Y and Z\./);
  assert.match(note, /model 49\.81 mm, photo 49\.83 mm, passed/);
  // a flat part whose box matches its footprint needs no note
  assert.equal(boxVsPhotoNote({ validity: { bbox_mm: [40.1, 20, 3] }, tests: [{ ...hook.tests[0], value: 40.05 }] }), null);
  assert.equal(boxVsPhotoNote({ validity: null, tests: [] }), null);
});

test("a stated thickness says it was used as given and checked only against itself; the side photo's number is its own", () => {
  // spacer j_261029_9771df9b: stated 8.50, side photo short side 8.15 vs model 8.08
  const residuals = [
    { feature_id: "side", quantity: "thickness", measured_mm: 8.149, model_mm: 8.076, delta_mm: -0.073, tol_mm: 0.3, passed: true },
    { feature_id: "plate", quantity: "thickness", measured_mm: 8.5, model_mm: 8.5, delta_mm: 0, tol_mm: 0.3, passed: true },
  ];
  const note = statedThicknessNote({ residuals }, "user_stated");
  assert.match(note, /^Thickness 8\.50 mm is the number you gave, used as given: .*\(model 8\.50 mm\), not the photo\./);
  assert.match(note, /The side photo's 8\.15 mm is a different measurement, the short side of its silhouette; its test compares the model's side outline \(8\.08 mm\) with it, within ±0\.30 mm \(passed\)\.$/);
  assert.equal(statedThicknessNote({ residuals }, "measured"), null);
  assert.equal(statedThicknessNote({ residuals: [] }, "user_stated"), null);
});

test("install-card panels are read from their labels, and movement steps on a still part get a note", () => {
  assert.deepEqual(installPanel("install card 3/3: Check that it moves and holds like the original (mock)"), { step: 3, of: 3, text: "Check that it moves and holds like the original", mock: true });
  assert.equal(installPanel("install card (mock)"), null);
  const labels = ["Take out the broken part", "Fit the printed part", "Check that it moves and holds like the original"];
  assert.match(installStepsNote("spacer", labels), /A spacer does not move: check that it sits flush and holds like the original\.$/);
  assert.equal(installStepsNote("hinge", labels), null);
  assert.equal(installStepsNote("spacer", ["Check that it sits flush and holds firmly"]), null);
  assert.equal(installStepsNote(null, labels), null);
});
