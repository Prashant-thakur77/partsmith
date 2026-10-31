import assert from "node:assert/strict";
import test from "node:test";
import { isDebugNote, plainTerms, splitNotes } from "../src/lib/plain-terms.ts";

test("technical terms read in plain words; numbers untouched", () => {
  assert.equal(
    plainTerms("tests 14/17; still failing: P0 test bbox.x: length (long side of the footprint) == 49.83 +/- 0.3 mm"),
    "tests 14/17; still failing: required test: length (long side of the footprint) == 49.83 +/- 0.3 mm",
  );
  assert.equal(plainTerms("top: IoU 0.797, Hausdorff 4.52 mm"), "top: overlap (IoU) 0.797, outline gap 4.52 mm");
  assert.equal(plainTerms("mean contour distance 0.21 mm (needs <= 0.15 mm)"), "average edge gap 0.21 mm (needs <= 0.15 mm)");
  assert.equal(plainTerms("P1 checks never decide; bbox.y off"), "advisory checks never decide; width off");
});

test("alignment and per-view metric dumps go behind Details; findings stay with the verdict", () => {
  const reasons = [
    "top: refined in the photo frame by -0.15 deg, (-3.93, -2.12) mm on the mat",
    "side view (photo frame): IoU 0.875 (needs >= 0.97), Hausdorff 4.70 mm (needs <= 0.5 mm) (worst at x=-25.2, y=-18.3 mm) - fails",
    "hole_2 center_x: model -9.85 vs measured -8.96 mm (-0.89 mm, tolerance +/-0.3 mm).",
    "top view: length, width and holes compared like for like (model rendered with the photo's camera and measured with the same metrology code).",
  ];
  const { findings, details } = splitNotes(reasons);
  assert.deepEqual(findings, [reasons[1], reasons[2]]); // a view line that fails is a finding
  assert.equal(details.length, 2);
  assert.equal(isDebugNote("Test failed: width (short side of the footprint) == 11.91 +/- 0.3 mm (model: 11.58)."), false);
});

test("older agent lines about the keep rule say what it compares: closeness to passing, not max error", () => {
  assert.equal(
    plainTerms("committed round 6: arm_width 12.00→11.00 mm; Hausdorff 4.70→4.62 mm, not verified; worse than the best committed model — code keeps the best"),
    "committed round 6: arm_width 12.00→11.00 mm; outline gap 4.70→4.62 mm, not verified; not closer to passing than the best committed round (judged on how close every check is to passing, not on max error); code keeps that one",
  );
  assert.match(plainTerms("Hausdorff 4.43→4.70 mm, not verified; now the best model"), /now the closest to passing \(judged on how close every check is to passing, not on max error\)$/);
});
