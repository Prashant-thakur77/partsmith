// Unit tests for the human review helpers (node --test; no browser, no network).
import assert from "node:assert/strict";
import test from "node:test";
import { EventSchema, JobDetailSchema, JudgeSchema, LessonTrackSchema, ReviewDetailSchema, ReviewQueueSchema, ReviewStatsSchema } from "../src/lib/api-types.ts";
import {
  agentRows,
  agreementText,
  blocker,
  decisionBody,
  nudge,
  pinOutcome,
  reviewersLabel,
  scorecardSummary,
  sortQueue,
  trackText,
  uvClamped,
  uvFromPoint,
  zoomFrame,
  verdictText,
  waitingCount,
} from "../src/lib/review.ts";

test("pin u,v come from the rendered image box, so CSS scale and zoom do not change them", () => {
  // the same spot on a 400×300 image drawn at 1× (at 100,50) and at 2.5× (at 20,10)
  const small = { left: 100, top: 50, width: 400, height: 300 };
  const big = { left: 20, top: 10, width: 1000, height: 750 };
  const a = uvFromPoint(100 + 0.25 * 400, 50 + 0.6 * 300, small);
  const b = uvFromPoint(20 + 0.25 * 1000, 10 + 0.6 * 750, big);
  assert.deepEqual(a, { u: 0.25, v: 0.6 });
  assert.deepEqual(b, a);
  // a zoomed image whose box starts off-screen (negative left/top) still maps correctly
  assert.deepEqual(uvFromPoint(0, 0, { left: -500, top: -250, width: 2000, height: 1000 }), { u: 0.25, v: 0.25 });
});

test("a click outside the image or on an empty box gives no pin; dragging clamps to the edge", () => {
  const box = { left: 0, top: 0, width: 200, height: 100 };
  assert.equal(uvFromPoint(-1, 50, box), null);
  assert.equal(uvFromPoint(50, 101, box), null);
  assert.equal(uvFromPoint(5, 5, { left: 0, top: 0, width: 0, height: 0 }), null);
  assert.deepEqual(uvFromPoint(200, 100, box), { u: 1, v: 1 });
  assert.deepEqual(uvClamped(250, -20, box), { u: 1, v: 0 });
  assert.deepEqual(nudge({ u: 0.995, v: 0.5 }, "ArrowRight"), { u: 1, v: 0.5 });
  assert.deepEqual(nudge({ u: 0.5, v: 0.5 }, "ArrowUp", true), { u: 0.5, v: 0.45 });
  assert.equal(nudge({ u: 0.5, v: 0.5 }, "Enter"), null);
});

test("pin outcome text uses the server's before/after numbers or says they are missing", () => {
  assert.equal(pinOutcome({ before_mm: 0.84, after_mm: 0.213 }), "0.84 → 0.21 mm");
  assert.equal(pinOutcome({ before_mm: null, after_mm: null }), "not measurable here");
  assert.equal(pinOutcome({ before_mm: 0.5, after_mm: null }), "0.50 mm before · after not measured");
});

test("scorecard summary lists the four criteria in order and counts vetoes; malformed scores are dropped", () => {
  const j = JudgeSchema.parse({
    model: "muse-spark-1.3",
    mode: "mock",
    scores: [
      { criterion: "fit", score: 4, reason: "mock" },
      { criterion: "outline", score: 4, reason: "within 0.5 mm" },
      { criterion: "outline", score: 9, reason: "out of range" },
      { criterion: "colour", score: 3, reason: "unknown criterion" },
      { criterion: "features", score: 3, reason: "one hole small" },
      { criterion: "printability", score: 5, reason: "" },
    ],
    vetoes: [{ feature: "hole_1", issue: "too small for M3", severity: "blocking" }, { feature: "edge", issue: "sharp", severity: "minor" }],
    notes: "",
  });
  assert.equal(j.scores.length, 4);
  assert.equal(scorecardSummary(j), "outline 4 · features 3 · printability 5 · fit 4 · 1 blocking veto · 1 minor veto");
  assert.equal(scorecardSummary(null), "no scorecard");
  assert.equal(scorecardSummary(JudgeSchema.parse({ scores: "bad" })), "no scores");
});

test("the queue puts waiting items first, then running rounds, then decided ones, newest first in each", () => {
  const it = (job_id, status, updated_at) => ({ job_id, status, updated_at });
  const sorted = sortQueue([it("a", "accepted", 50), it("b", "waiting", 10), it("c", "improving", 99), it("d", "waiting", 30), it("e", "odd", 100), it("f", "rejected", 60)]);
  assert.deepEqual(sorted.map((x) => x.job_id), ["d", "b", "c", "f", "a", "e"]);
  assert.equal(waitingCount(sorted), 2);
});

test("agreement text appears only with at least one review and shows kappa only when the server computed it", () => {
  assert.equal(agreementText(ReviewStatsSchema.parse({ n: 0, agree: 0, kappa: null })), null);
  assert.equal(agreementText(ReviewStatsSchema.parse({ n: 1, agree: 1, kappa: null })), "Judge agreed with the reviewer in 1/1 review");
  assert.equal(agreementText(ReviewStatsSchema.parse({ n: 4, agree: 3, kappa: 0.5 })), "Judge agreed with the reviewer in 3/4 reviews (κ 0.50)");
  assert.equal(reviewersLabel(1), "1 reviewer");
});

test("decision bodies: improve needs a pin or a note, reject a reason; each action sends only its fields", () => {
  const pins = [{ key: 1, u: 0.2, v: 0.3, note: " further left " }, { key: 2, u: 0.7, v: 0.8, note: "" }];
  assert.equal(blocker("improve", { pins: [], note: " ", reason: "" }), "Add a pin on the photo, a note or a screenshot first.");
  assert.equal(blocker("improve", { pins: [], note: "square corner", reason: "" }), null);
  assert.equal(blocker("reject", { pins, note: "", reason: "" }), "Write a short reason.");
  assert.equal(blocker("accept", { pins: [], note: "", reason: "" }), null);
  assert.deepEqual(decisionBody("improve", { pins, note: " also thicker ", reason: "ignored", attachments: ["k1.png"] }), {
    action: "improve",
    pins: [{ u: 0.2, v: 0.3, note: "further left" }, { u: 0.7, v: 0.8, note: "" }],
    note: "also thicker",
    reason: "",
    rules: [],
    publish: false,
    attachments: ["k1.png"],
    why: "",
  });
  // a pasted screenshot alone is enough to send a part back
  assert.equal(blocker("improve", { pins: [], note: "", reason: "", attachments: ["k1.png"] }), null);
  const accept = decisionBody("accept", {
    pins,
    note: "",
    reason: "",
    rules: [{ text: "bracket: holes are M3 clearance", keep: true, source_pin: 1 }, { text: "one-off", keep: false, source_pin: null }, { text: "  ", keep: true, source_pin: 2 }],
    publish: true,
  });
  assert.deepEqual(accept.pins, []);
  assert.deepEqual(accept.rules, [{ text: "bracket: holes are M3 clearance", keep: true, source_pin: 1 }, { text: "one-off", keep: false, source_pin: null }]);
  assert.equal(accept.publish, true);
  assert.equal(decisionBody("reject", { pins, note: "x", reason: " wrong part " }).reason, "wrong part");
});

test("agent rows group the job's model calls by stage and model, in run order", () => {
  const call = (seq, stage, model, usd, ok = true) =>
    EventSchema.parse({ job: "j", seq, ts: seq, t: "model_call", provider: "meta", model, stage, mode: "live", tokens_in: 1, tokens_out: 1, ms: 100, usd, ok });
  const rows = agentRows([call(1, "understand", "muse-spark-1.3", 0.01), call(2, "build", "spark-open", 0.002), call(3, "fix", "spark-open", 0.003, false), call(4, "build", "spark-open", 0.002)]);
  assert.deepEqual(rows.map((r) => [r.stage, r.calls, r.failed]), [["understand", 1, 0], ["build", 2, 0], ["fix", 1, 1]]);
  assert.ok(Math.abs(rows[1].usd - 0.004) < 1e-12);
});

test("verdict text and lesson track text come straight from the API values", () => {
  assert.equal(verdictText({ status: "best_effort", max_error_mm: 0.834 }), "best effort · 0.83 mm");
  assert.equal(verdictText(null), "no verdict yet");
  assert.equal(trackText(null), null);
  assert.equal(trackText({ used_in: 0, accepted: 0, improved: 0, rejected: 0 }), "Not used in a job yet");
  assert.equal(trackText({ used_in: 3, accepted: 1, improved: 1, rejected: 0 }), "Used in 3 jobs · later reviews: 1 accepted, 1 sent back, 0 rejected");
});

test("older APIs still parse: job detail without judge/review, partial track and review payloads", () => {
  const job = JobDetailSchema.parse({ summary: { id: "j", kind: "fix", status: "done", created_at: 1, updated_at: 2 } });
  assert.equal(job.judge ?? null, null);
  assert.equal(job.review ?? null, null);
  const bad = JobDetailSchema.parse({ summary: { id: "j", kind: "fix", status: "done", created_at: 1, updated_at: 2 }, judge: 7, review: "x" });
  assert.equal(bad.judge, null);
  assert.equal(bad.review, null);
  assert.deepEqual(LessonTrackSchema.parse({ used_in: 2 }), { used_in: 2, accepted: 0, improved: 0, rejected: 0 });
  const q = ReviewQueueSchema.parse({ items: [{ job_id: "a", status: "waiting" }, { nope: true }] });
  assert.equal(q.items.length, 1);
  assert.equal(q.items[0].round, 1);
  const d = ReviewDetailSchema.parse({ root_job: "a", status: "waiting", rounds: [{ round: 1, job_id: "a", pins: [{ id: 1, u: 0.1, v: 0.2 }] }] });
  assert.equal(d.rounds[0].pins[0].before_mm ?? null, null);
  assert.equal(d.images.rectified ?? null, null);
});

test("zoomFrame shows only the part's box and keeps pins on the full photo", () => {
  const z = zoomFrame([0.25, 0.5, 0.5, 0.75], { w: 1600, h: 800 });
  assert.ok(z);
  assert.equal(z.width, 400); // the full image is 4× the frame's width
  assert.equal(z.left, -100);
  assert.equal(z.top, -200);
  assert.equal(z.aspect, (0.25 * 1600) / (0.25 * 800));
  // a click at the frame's centre is u = left edge + half the box: the full image's own box decides (u, v)
  const frame = { left: 0, top: 0, width: 400, height: 200 };
  const img = { left: frame.left + (z.left / 100) * frame.width, top: frame.top + (z.top / 100) * frame.height, width: (z.width / 100) * frame.width, height: (z.width / 100) * frame.width * (800 / 1600) };
  assert.deepEqual(uvFromPoint(200, 100, img), { u: 0.375, v: 0.625 });
  assert.equal(zoomFrame([0, 0, 0.95, 0.9], { w: 100, h: 100 }), null); // already most of the image
  assert.equal(zoomFrame(null, { w: 100, h: 100 }), null);
  assert.equal(zoomFrame([0.1, 0.1, 0.2, 0.2], null), null); // image size not known yet
});
