// Landing art and motion helpers (node --test; no browser): count-ups land exactly on the API's text, the drawing maps
// millimetres into the figure, and the stored runs are picked from /replays alone.
import assert from "node:assert/strict";
import test from "node:test";
import { countFrame, countText, decimalsOf, easeOutCubic, splitNumeric, stepIndex } from "../src/lib/count-up.ts";
import { arcPath, fitPoints, gaugeRadius, markerBits, nearestIndex, offsetOutline, pathOf, signedArea } from "../src/lib/drawing.ts";
import { figureFromJob, knobLines, measuredValue, measureLinks, pickFigureRun, pickLoopRun, pickReviewRun } from "../src/lib/figure-run.ts";

test("count-up: the last frame is exactly the formatted value from the API", () => {
  for (const text of ["0.10 mm", "17/17", "US$25.75", "₹1,200.00", "3", "N = 12"]) assert.equal(countText(text, 1), text);
  assert.equal(countText("0.10 mm", 0), "0.00 mm");
  assert.equal(countText("17/17", 0), "0/17");
  assert.equal(countText("no number", 0.5), "no number");
});

test("count-up: numbers keep their decimals and prefix/suffix on the way", () => {
  assert.deepEqual(splitNumeric("US$25.75"), { prefix: "US$", value: 25.75, decimals: 2, suffix: "", grouped: false });
  assert.deepEqual(splitNumeric("₹1,200.00"), { prefix: "₹", value: 1200, decimals: 2, suffix: "", grouped: true });
  assert.equal(splitNumeric("—"), null);
  assert.equal(decimalsOf("4.25"), 2);
  assert.equal(decimalsOf("17"), 0);
  assert.equal(countFrame(0.5, 0.5, 2), "0.44"); // ease-out: 87.5 % of the way at half time
  assert.equal(countText("₹1,200.00", 0.5), "₹1,050.00");
  assert.equal(easeOutCubic(-1), 0);
  assert.equal(easeOutCubic(2), 1);
});

test("count-up: a stepping counter holds each value and stops at the last", () => {
  const v = [2.69, 0.51, 0.39];
  assert.equal(stepIndex(v, 0, 1000), 0);
  assert.equal(stepIndex(v, 1500, 1000), 1);
  assert.equal(stepIndex(v, 99_000, 1000), 2);
  assert.equal(stepIndex([], 10, 1000), -1);
  assert.equal(stepIndex(v, 10, 0), 2);
});

test("drawing: a measured outline is centred and scaled into the box, y flipped", () => {
  const sq = [[-10, -5], [10, -5], [10, 5], [-10, 5]];
  const f = fitPoints(sq, { x: 0, y: 0, w: 200, h: 100 });
  assert.equal(f.scale, 10);
  assert.deepEqual(f.map([-10, 5]), [0, 0]); // top-left in svg is (min x, max y) in mm
  assert.deepEqual(f.map([10, -5]), [200, 100]);
  assert.deepEqual(f.bbox, { x: 0, y: 0, w: 200, h: 100 });
  assert.equal(pathOf(sq, f.map), "M0 100 L200 100 L200 0 L0 0 Z");
  assert.equal(pathOf([], f.map), "");
});

test("drawing: offsetting grows a polygon outwards whichever way it winds", () => {
  const ccw = [[0, 0], [10, 0], [10, 10], [0, 10]];
  const cw = [...ccw].reverse();
  assert.ok(signedArea(ccw) > 0 && signedArea(cw) < 0);
  for (const poly of [ccw, cw]) {
    const out = offsetOutline(poly, 1);
    assert.ok(Math.abs(signedArea(out)) > Math.abs(signedArea(poly)));
  }
  assert.equal(nearestIndex(ccw, [9, 9]), 2);
});

test("drawing: marker patterns are stable, 16 bits, and never a solid row", () => {
  for (let id = 0; id < 40; id++) {
    const b = markerBits(id);
    assert.equal(b.length, 16);
    assert.deepEqual(markerBits(id), b);
    for (let r = 0; r < 4; r++) {
      const row = b.slice(r * 4, r * 4 + 4);
      assert.ok(row.some(Boolean) && row.some((x) => !x), `marker ${id} row ${r}`);
    }
  }
  assert.notDeepEqual(markerBits(1), markerBits(2));
});

test("drawing: loop ring arcs and the error gauge", () => {
  assert.equal(arcPath(0, 0, 10, 0, 90), "M0 -10 A10 10 0 0 1 10 0");
  assert.equal(gaugeRadius(0, 3, 18, 96), 18);
  assert.equal(gaugeRadius(3, 3, 18, 96), 96);
  assert.equal(gaugeRadius(9, 3, 18, 96), 96);
  assert.equal(gaugeRadius(Number.NaN, 3, 18, 96), 18);
});

const r = (id, title, verified, max_error_mm, iterations) => ({ id, title, origin: "synthetic", provider_mode: "live", verified, max_error_mm, iterations });
const LIST = [
  r("a", "Hinge leaf (synthetic, clean)", false, 3.68, 6),
  r("b", "SD card (synthetic, clean)", true, 0.47, 1),
  r("c", "Battery cover (synthetic, clean)", true, 0.39, 3),
  r("d", "Hinge leaf (synthetic, clean) · review round 3", false, 0.38, 7),
  r("e", "Hinge leaf (synthetic, clean) · review round 4", true, 0.38, 2),
];

test("stored runs: Fig. 1 takes the verified end of a review chain, the loop the run fixed over most rounds", () => {
  assert.equal(pickFigureRun(LIST).id, "e");
  assert.equal(pickLoopRun(LIST).id, "c");
  assert.equal(pickReviewRun(LIST).id, "e");
  const noReview = LIST.filter((x) => !x.title.includes("review"));
  assert.equal(pickFigureRun(noReview).id, "c");
  assert.equal(pickReviewRun(noReview), null);
  assert.equal(pickFigureRun([]), null);
  assert.equal(pickLoopRun([r("z", "Clip", false, 1.2, 4)]).id, "z");
});

const CODE = `import cadquery as cq
MEASURE_MAP = {
    "length": "length",
    "width": "leaf_width",
    "hole_1.diameter": "hole_d",
    "side.thickness": "pin_d",
}

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "length": (58.4, 24.0, 120.0, 0.1, "mm", True, "Hinge length"),
    "leaf_width": (29.2, 14.0, 60.0, 0.1, "mm", True, "Leaf width"),
    "hole_d": (4.25, 2.0, 6.0, 0.05, "mm", True, "Screw hole diameter"),
}


def build(p):
    return cq.Workplane("XY")
`;

test("program lines: the PARAMS block with the knob each line names, and the measured-size links", () => {
  const lines = knobLines(CODE, ["length", "leaf_width", "hole_d"]);
  assert.equal(lines[0].text.trim().startsWith("PARAMS"), true);
  assert.deepEqual(lines.slice(1, 4).map((l) => l.knob), ["length", "leaf_width", "hole_d"]);
  assert.equal(lines.at(-1).text.trim(), "}");
  assert.deepEqual(knobLines(null, ["x"]), []);
  assert.deepEqual(measureLinks(CODE), [
    { measure: "length", knob: "length" },
    { measure: "width", knob: "leaf_width" },
    { measure: "hole_1.diameter", knob: "hole_d" },
    { measure: "side.thickness", knob: "pin_d" },
  ]);
  const f = { lengthMm: 58.54, widthMm: 29.67, holes: [{ id: "hole_1", center: [0, 0], diameterMm: 4.23 }] };
  assert.equal(measuredValue(f, "length"), 58.54);
  assert.equal(measuredValue(f, "hole_1.diameter"), 4.23);
  assert.equal(measuredValue(f, "side.thickness"), null);
});

test("figure data: numbers are read from the job detail, top-view artifacts first", () => {
  const ev = (e) => ({ job: "j", seq: 0, ts: 0, ctx: "", ...e });
  const d = {
    summary: { id: "j", title: "Hinge leaf · review round 4", origin: "synthetic", provider_mode: "live", verified: true, max_error_mm: 0.38 },
    measurements: { top: { outline_mm: [[0, 0], [1, 0], [1, 1]], holes: [{ id: "hole_1", center_mm: [0.5, 0.5], diameter: { value: 4.23 } }], length: { value: 58.54 }, width: { value: 29.67 } } },
    verification: { verified: true, status: "verified", max_error_mm: 0.376, thresholds: { hausdorff_mm: 0.5 }, views: [{ view: "top", hausdorff_mm: 0.376, worst_point_mm: [-28.4, 13.4] }] },
    events: [
      ev({ t: "artifact", kind: "rectified", url: "/top.png", label: "top: rectified" }),
      ev({ t: "artifact", kind: "rectified", url: "/side.png", label: "side: rectified" }),
      ev({ t: "iteration", iter: 1, hausdorff_mm: 2.69 }),
      ev({ t: "iteration", iter: 2, hausdorff_mm: null }),
      ev({ t: "iteration", iter: 3, hausdorff_mm: 0.39 }),
    ],
    artifacts: { view: "/view.json", photo: "/photo.jpg" },
    values: { length: 58.4 },
    params: [],
    code: null,
  };
  const f = figureFromJob(d);
  assert.equal(f.lengthMm, 58.54);
  assert.equal(f.limitMm, 0.5);
  assert.equal(f.maxErrorMm, 0.376);
  assert.deepEqual(f.worst, { at: [-28.4, 13.4], gapMm: 0.376 });
  assert.deepEqual(f.rounds, [{ iter: 1, mm: 2.69 }, { iter: 3, mm: 0.39 }]);
  assert.equal(f.rectified, "/top.png");
  assert.equal(f.photo, "/photo.jpg");
  assert.equal(f.viewUrl, "/view.json");
  assert.deepEqual(f.holes, [{ id: "hole_1", center: [0.5, 0.5], diameterMm: 4.23 }]);
});
