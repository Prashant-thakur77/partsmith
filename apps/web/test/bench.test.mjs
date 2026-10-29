// Bench headline formatting (node --test; no browser). Reads the committed live report.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { benchHeadline } from "../src/lib/bench.ts";

const REPORT = JSON.parse(readFileSync(new URL("../../../eval/reports/latest/report.json", import.meta.url), "utf8"));

test("expected-outcome suites show cases handled as expected, never millimetres", () => {
  for (const key of ["control", "redteam"]) {
    const t = REPORT.tables[key];
    if (t.status !== "ok") continue;
    const h = benchHeadline(t);
    assert.equal(h?.value, `${t.headline.correct}/${t.headline.n}`);
    assert.doesNotMatch(h.value, /mm/);
  }
});

test("a dimension suite shows its _mm headline as a length", () => {
  const h = benchHeadline({ status: "ok", n: 12, ground_truth: "synthetic_exact", headline: { config: "PS", median_abs_err_mm: 0.1 } });
  assert.equal(h?.value, "0.10 mm");
  const c = benchHeadline({ status: "ok", n: 3, ground_truth: "ruler", headline: { iterations: 4 } });
  assert.equal(c?.value, "4");
});
