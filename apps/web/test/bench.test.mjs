// Bench headline formatting (node --test; no browser). Reads the committed live report.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { benchHeadline, benchSentence, benchVerified, columnLabel, configLabel, passVsVerifiedNote, plainBench } from "../src/lib/bench.ts";

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

test("the plain sentence is built from the headline's own numbers", () => {
  const s = benchSentence("synthetic", { status: "ok", n: 12, headline: { config: "PS", median_abs_err_mm: 0.1, pass_at_0_5: 0.25, verified_rate: 0.167, n: 12 } });
  assert.equal(s, "On 12 rendered test photos the full pipeline's median size error was 0.10 mm; 3 of 12 had every size within 0.5 mm, and 2 of 12 passed the code's check.");
  assert.equal(benchSentence("redteam", { status: "ok", n: 10, headline: { correct: 10, n: 10 } }), "10 of 10 photos that should be turned away were handled as expected (rejected or refused).");
  assert.equal(benchSentence("real_ruler", { status: "pending", n: 0, headline: { median_abs_err_mm: null } }), null);
  for (const key of Object.keys(REPORT.tables)) benchSentence(key, REPORT.tables[key]); // never throws on the real report
});

test("column ids get plain headers; unknown ids stay readable", () => {
  assert.equal(columnLabel("median_abs_err_mm"), "Median size error (mm)");
  assert.equal(columnLabel("pass@0.8"), "All sizes within 0.8 mm of truth");
  assert.equal(columnLabel("pass@0.5"), "All sizes within 0.5 mm of truth");
  assert.equal(columnLabel("weird_thing_mm"), "weird thing (mm)");
});

test("a table with both a size-pass column and Verified explains why they differ", () => {
  const note = passVsVerifiedNote(REPORT.tables.synthetic.columns);
  assert.match(note, /^“All sizes within 0\.5 mm of truth” compares every measured size/);
  assert.match(note, /also needs the outline to match the photo and the part tests to pass/);
  assert.equal(passVsVerifiedNote(["config", "verified_rate"]), null);
  assert.equal(passVsVerifiedNote(["config", "pass@0.5"]), null);
});

test("the verified count comes from the headline's verified_rate and n (same cases as the median)", () => {
  assert.deepEqual(benchVerified({ status: "ok", n: 12, headline: { median_abs_err_mm: 0.1, verified_rate: 0.167, n: 12 } }), { passed: 2, n: 12 });
  assert.equal(benchVerified({ status: "pending", n: 0, headline: {} }), null);
  assert.equal(benchVerified({ status: "ok", n: 6, headline: { correct: 6, n: 6 } }), null);
  assert.equal(benchVerified(undefined), null);
  const t = REPORT.tables.synthetic;
  if (t.status === "ok" && typeof t.headline.verified_rate === "number") {
    assert.equal(benchVerified(t)?.n, t.headline.n ?? t.n);
  }
});

test("report ids read as plain words: no bare PS, no underscores", () => {
  assert.equal(plainBench("syn-hook-glare-s235877 · PS (synthetic, held_out)"), "syn-hook-glare-s235877 · full pipeline (synthetic, held-out)");
  assert.equal(plainBench("headline = PS on the held-out split (12 samples)"), "headline = PartSmith (full pipeline) on the held-out split (12 samples)");
  assert.equal(plainBench("ref-aa · PS (reference_objects, held_out)"), "ref-aa · full pipeline (reference objects, held-out)");
  assert.equal(plainBench("PS-noJudge vs B1"), "Loop, no judge vs One shot, no loop");
  assert.equal(configLabel("PS"), "PartSmith (full pipeline)");
  assert.equal(columnLabel("verified_but_off"), "Verified, yet a size over 0.5 mm off");
});
