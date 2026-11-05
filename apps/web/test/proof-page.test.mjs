// The proof client's schema accepts what the API really builds from the committed reports' shapes, and rates read plainly.
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";
import { maskSourceTotals, ProofSchema, rateText, ScaleSchema } from "../src/lib/proof-schema.ts";

test("rates print as k of n with their interval, and a missing rate is absent", () => {
  assert.deepEqual(rateText({ k: 3, n: 4, ci95: [0.3, 0.95] }), { headline: "3 of 4", ci: "[0.3, 0.95]" });
  assert.deepEqual(rateText({ k: 3, n: 4 }), { headline: "3 of 4", ci: null });
  assert.equal(rateText(null), null);
});

test("an empty server still parses, with nothing invented", () => {
  const p = ProofSchema.parse({
    report_date: null,
    errors: [],
    outcomes: [],
    instruments: [],
    tests: { gates: [], source: "eval/reports/latest/tests.json" },
    audit: [],
    scale: null,
    not_tested: { real_phone_photos_measured: 0, real_parts_with_ruler_ground_truth: 0, real_prints_or_repairs_logged: 0, person_reviewed_rounds: 0, scripted_review_decisions: 0 },
  });
  assert.equal(p.scale, null);
});

test("the stored scale report parses, whichever shape the evaluation wrote, and its outline sources are counted", () => {
  const path = new URL("../../../eval/reports/latest/scale.json", import.meta.url);
  assert.equal(maskSourceTotals(null), null);
  assert.deepEqual(maskSourceTotals({ a: { threshold: 3, "sam-3.1": 1, "no measure line": 5 }, b: { "sam-3.1": 2 } }), { sam: 3, measured: 6 });
  if (!existsSync(path)) return;
  const raw = JSON.parse(readFileSync(path, "utf8"));
  const parsed = ScaleSchema.parse({ ...raw, source: "eval/reports/latest/scale.json", command: "x" });
  assert.equal(parsed.sam.mask_returned.n, raw.sam.mask_returned.n);
  assert.equal(parsed.understanding.family_correct.k, raw.understanding.family_correct.k);
  const totals = maskSourceTotals(parsed.mask_sources);
  assert.ok(totals.measured > 0 && totals.sam <= totals.measured);
});
