// /how's eight steps, the glossary and the plain summaries (node --test; no browser). Reads the committed reports and run data.
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";
import { resultsPlain } from "../src/lib/bench.ts";
import { GLOSSARY, GLOSSARY_KEYS, splitTerms } from "../src/lib/glossary.ts";
import { FLOW_STEPS, FlowDataSchema, stepFacts } from "../src/lib/how-flow.ts";
import { jobPlain } from "../src/lib/plain-summary.ts";

const DECK = JSON.parse(readFileSync(new URL("../public/deck/data.json", import.meta.url), "utf8"));
const REPORT = JSON.parse(readFileSync(new URL("../../../eval/reports/latest/report.json", import.meta.url), "utf8"));

const job = (over = {}) => ({
  status: "done",
  finished: "verified",
  maxErrorMm: 0.39,
  limitMm: 0.5,
  gaps: [2.69, 0.51, 0.39],
  views: [{ view: "top", iou: 0.987 }],
  tests: [{ passed: true }, { passed: true }],
  uncheckedCount: 0,
  failingCheck: null,
  finding: null,
  refusal: null,
  inReview: false,
  recorded: false,
  sample: false,
  mock: false,
  ...over,
});

test("the glossary covers the five words and each has a plain sentence", () => {
  assert.deepEqual(GLOSSARY_KEYS, ["hausdorff", "iou", "parametric", "verifier", "mat"]);
  for (const key of GLOSSARY_KEYS) assert.ok(GLOSSARY[key].text.endsWith("."), key);
});

test("splitTerms marks the first use of each word and keeps every other character", () => {
  const text = "The verifier's outline gap and overlap (IoU) on the screen mat; the verifier again.";
  const pieces = splitTerms(text);
  assert.equal(pieces.map((p) => (typeof p === "string" ? p : p.word)).join(""), text);
  assert.deepEqual(
    pieces.filter((p) => typeof p !== "string").map((p) => [p.key, p.word]),
    [
      ["verifier", "verifier's"],
      ["hausdorff", "outline gap"],
      ["iou", "IoU"],
      ["mat", "screen mat"],
    ],
  );
  assert.deepEqual(splitTerms("nothing to explain"), ["nothing to explain"]);
  assert.deepEqual(splitTerms("a format, a matter"), ["a format, a matter"]);
});

test("verified: says it passed with the record's numbers and keeps the sizes nothing checked in view", () => {
  const plain = jobPlain(job({ uncheckedCount: 6 }));
  assert.equal(plain.tone, "ok");
  assert.equal(plain.happened, "Passed. The largest error is 0.39 mm; the limit is 0.50 mm.");
  assert.ok(plain.why.includes("Outline gap by round: 2.69 → 0.51 → 0.39 mm."));
  assert.ok(plain.why.includes("Overlap with the photo (IoU): top 0.987."));
  assert.ok(plain.why.includes("2 of 2 part tests passed."));
  assert.ok(plain.why.includes("6 sizes had no photo to check them against; they are listed below."));
  assert.deepEqual(plain.actions, ["fit", "model"]);
  assert.equal(jobPlain(job({ gaps: [0.3] })).why[1], "It passed on the first build.");
});

test("not verified: never reads as a pass, and names what failed", () => {
  const over = jobPlain(job({ finished: "best_effort", maxErrorMm: 0.83, finding: "the top outline is off by up to 0.83 mm (limit 0.50 mm)" }));
  assert.equal(over.tone, "warn");
  assert.equal(over.happened, "Not verified. The closest model is 0.83 mm off; the limit is 0.50 mm.");
  assert.ok(over.why[0].startsWith("the top outline"));
  assert.match(over.next, /Retake the photo/);

  const inside = jobPlain(job({ finished: "best_effort", maxErrorMm: 0.38, failingCheck: "side outline" }));
  assert.equal(inside.happened, "Not verified. The largest error, 0.38 mm, is inside the 0.50 mm limit, but the side outline check failed.");

  const judge = jobPlain(job({ finished: "best_effort", maxErrorMm: 0.38, failingCheck: "judge flag", inReview: true }));
  assert.match(judge.happened, /but the judge blocked it\.$/);
  assert.match(judge.next, /Read the judge's note/);
  assert.deepEqual(judge.actions, ["review", "fix", "model"]);

  const recorded = jobPlain(job({ finished: "best_effort", recorded: true }));
  assert.match(recorded.next, /recorded run will not change/);

  for (const finished of ["best_effort", "failed", "refused", "cancelled"]) {
    const plain = jobPlain(job({ finished }));
    assert.notEqual(plain.tone, "ok", finished);
    assert.doesNotMatch(plain.happened, /^Passed/, finished);
  }
  assert.equal(jobPlain(job({ finished: "refused", refusal: "soft part" })).why[0], "soft part");
  assert.deepEqual(jobPlain(job({ finished: "refused" })).actions, ["fix"]);
});

test("running and paused jobs say so, with the latest gap and nothing to export", () => {
  const running = jobPlain(job({ status: "running", finished: null, gaps: [2.69], maxErrorMm: null }));
  assert.equal(running.tone, "busy");
  assert.equal(running.happened, "Working on it. The latest outline gap is 2.69 mm; the limit is 0.50 mm.");
  assert.equal(jobPlain(job({ status: "queued", finished: null, gaps: [] })).happened, "Waiting to start.");
  const paused = jobPlain(job({ status: "waiting_for_answer", finished: null, gaps: [] }));
  assert.match(paused.happened, /^Paused/);
  assert.deepEqual(paused.actions, []);
});

test("the label says recorded, rendered or mock, and stays quiet on a real live run", () => {
  assert.equal(jobPlain(job()).label, null);
  assert.equal(jobPlain(job({ sample: true })).label, "Rendered sample photo, not a phone capture.");
  assert.match(jobPlain(job({ recorded: true, sample: true })).label, /^Recorded run on a rendered sample photo: played back/);
  assert.match(jobPlain(job({ mock: true })).label, /^Mock run/);
});

test("results in plain words: four answers from the report's own headlines, and real parts stay at not measured", () => {
  const rows = resultsPlain(REPORT.tables, REPORT.separate_tables);
  assert.deepEqual(rows.map((r) => r.key), ["synthetic", "public_photos", "redteam", "real_ruler"]);
  const syn = REPORT.tables.synthetic.headline;
  assert.ok(rows[0].answer.includes(`${syn.median_abs_err_mm.toFixed(2)} mm`), rows[0].answer);
  const pub = REPORT.separate_tables.public_photos.headline;
  assert.ok(rows[1].answer.includes(`${pub.median_abs_err_mm.toFixed(2)} mm`), rows[1].answer);
  const red = REPORT.tables.redteam.headline;
  assert.ok(rows[2].answer.includes(`${red.correct} of ${red.n}`), rows[2].answer);
  if (!REPORT.tables.real_ruler.n) assert.match(rows[3].answer, /^Not measured yet/);
  const empty = resultsPlain({}, {});
  assert.match(empty[0].answer, /has not run yet/);
  assert.match(empty[3].answer, /^Not measured yet/);
});

test("how: eight steps, each with plain words and a reason, and every picture is a real file", () => {
  assert.equal(FLOW_STEPS.length, 8);
  assert.equal(new Set(FLOW_STEPS.map((s) => s.id)).size, 8);
  for (const step of FLOW_STEPS) {
    assert.ok(step.plain.length > 40 && step.proof.length > 40, step.id);
    assert.ok(step.links.length > 0, step.id);
    for (const image of step.images) {
      assert.ok(existsSync(new URL(`../public${image.src}`, import.meta.url)), image.src);
      assert.ok(image.alt && image.caption, image.src);
    }
  }
  // the one step without a picture shows the program's own lines
  assert.deepEqual(FLOW_STEPS.filter((s) => !s.images.length).map((s) => s.id), ["program"]);
});

test("how: the steps' numbers are the run's own, nothing typed", () => {
  const data = FlowDataSchema.parse(DECK);
  const rounds = data.run.rounds_detail;
  const check = stepFacts("check", data);
  assert.ok(check[0].includes(`${rounds[0].error_mm} mm off`), check[0]);
  assert.ok(check[0].includes(`The limit is ${data.limit_mm} mm`), check[0]);
  assert.ok(check[1].includes(`blocked ${data.bypass.blocked} of ${data.bypass.attempts} times`), check[1]);
  const fix = stepFacts("fix", data);
  assert.equal(fix.length, rounds.length);
  assert.ok(fix.at(-1).startsWith(`Round ${rounds.at(-1).round}: ${rounds.at(-1).error_mm} mm`), fix.at(-1));
  assert.ok(fix[1].includes(`${rounds[1].edits[0].param} ${rounds[1].edits[0].from} → ${rounds[1].edits[0].to}`), fix[1]);
  const review = stepFacts("review", data);
  assert.ok(review[0].includes(`${data.run.minutes_to_file} minutes`), review[0]);
  assert.ok(review[1].includes("It has not been printed."), review[1]);
  assert.deepEqual(stepFacts("photo", data), []);
});
