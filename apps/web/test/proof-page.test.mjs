// The proof client's schema accepts what the API really builds from the committed reports' shapes, and rates read plainly.
import assert from "node:assert/strict";
import test from "node:test";
import { ProofSchema, rateText } from "../src/lib/proof-schema.ts";

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
