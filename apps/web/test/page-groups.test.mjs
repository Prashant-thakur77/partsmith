// Unit tests for list shaping: lessons grouping, the jobs summary and filters, the feedback log by part, local origins.
import assert from "node:assert/strict";
import test from "node:test";
import {
  allTests,
  filterJobs,
  groupFeedback,
  groupLessons,
  groupLinks,
  isLocalOrigin,
  jobBucket,
  jobsSummary,
  jobsSummaryText,
  knobRuns,
  lessonText,
  lessonKey,
  median,
  parseJobFilter,
  passRateText,
  groupJobAttempts,
  groupQueueAttempts,
  moreAttemptsText,
  RUN_WORDS,
  runCounts,
  runSplitText,
  buildsUsing,
  lessonConflict,
} from "../src/lib/page-groups.ts";

test("local origins are the ones a phone cannot open", () => {
  for (const o of ["http://127.0.0.1:3766", "http://localhost:3000", "http://[::1]:3000", "http://0.0.0.0:80", "http://app.localhost"]) assert.equal(isLocalOrigin(o), true, o);
  for (const o of ["https://partsmith.example", "http://192.168.1.20:3000", "not a url"]) assert.equal(isLocalOrigin(o), false, o);
});

const link = (id) => ({ kind: "job", id, page: `/jobs/${id}` });
const lesson = (id, over = {}) => ({ id, scope: "cover", rule: `rule ${id}`, status: "candidate", created_at: 0, evidence: {}, links: [link(`j_${id}`)], ...over });

test("lessons on the same template knob or with the same text share one card, newest wording first", () => {
  const list = [
    lesson("a", { created_at: 1, rule: "corner_radius: 1 → 1.9", evidence: { template: "battery_cover", param: "corner_radius", first: 1, final: 1.9 } }),
    lesson("b", { created_at: 3, rule: "corner_radius: 1 → 2.4", evidence: { template: "battery_cover", param: "corner_radius", first: 1, final: 2.4 } }),
    lesson("c", { created_at: 2, rule: "Same  words" }),
    lesson("d", { created_at: 4, rule: "same words", links: [link("j_c"), link("j_d")] }),
    lesson("e", { created_at: 5, rule: "corner_radius: 1 → 2.4", status: "rejected", evidence: { template: "battery_cover", param: "corner_radius" } }),
    lesson("f", { created_at: 6, scope: "hook", rule: "hook rule" }),
  ];
  assert.notEqual(lessonKey(list[0]), lessonKey(list[4]), "status splits groups");
  const fams = groupLessons(list);
  assert.deepEqual(fams.map((f) => [f.scope, f.lessons, f.groups.length]), [["cover", 5, 3], ["hook", 1, 1]]);
  const [words, knob] = fams[0].groups; // equal sizes: the group with the newer lead comes first
  assert.equal(fams[0].groups[2].lead.id, "e");
  assert.deepEqual(knob.members.map((m) => m.id), ["b", "a"]);
  assert.equal(knob.lead.id, "b");
  assert.deepEqual(knobRuns(knob.members).map((r) => [r.job, r.first, r.final]), [["j_b", 1, 2.4], ["j_a", 1, 1.9]]);
  assert.deepEqual(words.members.map((m) => m.id), ["d", "c"]);
  assert.deepEqual(groupLinks(words.members).map((l) => l.id), ["j_c", "j_d"], "links are not repeated");
});

test("a knob lesson is worded from its evidence and follows how its run ended", () => {
  const ev = { template: "cable_clip", param: "hole_d", first: 6, final: 6.7, verified: false, max_error_mm: 4.8 };
  const best = lessonText({ rule: "cable_clip: the first build set hole_d = 6, the verified loop moved it to 6.7", evidence: ev }, "Hole diameter");
  assert.equal(best, "Cable Clip: the first build set Hole diameter = 6; the fix loop moved it to 6.7 (+0.70) in a run that ended best effort (max gap 4.80 mm), so the final value is not confirmed. Check Hole diameter against the measurement before building.");
  assert.doesNotMatch(best, /verified/);
  const person = "Start hole_d 0.3 mm above the measured diameter for FDM prints.";
  assert.equal(lessonText({ rule: person, evidence: ev }), person, "a person's wording is never rewritten");
  assert.match(lessonText({ rule: "cable_clip: the first build set hole_d = 6, …", evidence: { ...ev, verified: true, max_error_mm: 0.31, final: 5.5 } }), /^Cable Clip: the first build set Hole D = 6; .* \(−0\.50\) in a run that passed verification \(max gap 0\.31 mm\)\./);
  assert.equal(lessonText({ rule: "battery_cover: strategy switched (x).", evidence: {} }), "Battery Cover: strategy switched (x).");
});

const job = (status, verified, max_error_mm, over = {}) => ({ status, verified, max_error_mm, is_replay: false, origin: "synthetic", ...over });

test("the jobs summary and filters come from the list itself", () => {
  const list = [
    job("done", true, 0.3),
    job("done", true, 0.1, { is_replay: true }),
    job("done", false, 2.0),
    job("failed", false, null),
    job("running", false, null, { origin: "replay" }),
    job("cancelled", false, 9.0),
  ];
  assert.deepEqual(list.map(jobBucket), ["verified", "verified", "best_effort", "failed", "in_progress", "failed"]);
  const s = jobsSummary(list);
  assert.equal(s.n, 6);
  assert.equal(s.verified, 2);
  assert.deepEqual(s.source, { recorded: 2, server: 4 });
  assert.equal(s.gapN, 3, "only finished jobs with a gap count");
  assert.equal(s.medianMaxGapMm, 0.3);
  assert.deepEqual(s.server, { verified: 1, finished: 3 }, "made here, done or failed: the admin overview's set");
  assert.equal(jobsSummaryText(s), "2 of 6 listed verified · median max gap 0.30 mm (3 with a measured gap) · made here: 1 verified of 3 finished (done or failed)");
  assert.equal(jobsSummaryText(jobsSummary([job("failed", false, null)])), "0 of 1 listed verified");
  assert.deepEqual(parseJobFilter("verified", "nope"), { status: "verified", source: null });
  assert.deepEqual(parseJobFilter("bogus", "recorded"), { status: null, source: "recorded" });
  assert.equal(filterJobs(list, { status: "verified", source: "server" }).length, 1);
  assert.equal(filterJobs(list, { status: null, source: "recorded" }).length, 2);
  assert.equal(median([3, 1, 2, 4]), 2.5);
  assert.equal(median([]), null);
});

test("one vocabulary for run counts: listed = made here + recorded, finished = done or failed", () => {
  const c = runCounts({ jobs: 22, jobs_recorded: 3, jobs_listed: 25 });
  assert.deepEqual(c, { listed: 25, madeHere: 22, recorded: 3 }, "home counts what /jobs lists");
  assert.equal(c.listed, c.madeHere + c.recorded);
  assert.deepEqual(runCounts({ jobs: 4 }), { listed: 4, madeHere: 4, recorded: 0 });
  assert.equal(runSplitText(c), "22 made here · 3 recorded");
  assert.equal(runSplitText({ madeHere: 4, recorded: 0 }), "4 made here");
  assert.equal(passRateText(6, 22), "6 verified of 22 finished (done or failed)");
  assert.equal(RUN_WORDS.finished, "finished (done or failed)");
  // the /jobs chips count the same sets the home strip names
  const list = [job("done", true, 0.3), job("failed", false, null), job("done", false, 1, { is_replay: true })];
  const s = jobsSummary(list);
  assert.deepEqual({ madeHere: s.source.server, recorded: s.source.recorded, listed: s.n }, { madeHere: 2, recorded: 1, listed: 3 });
  // "finished" never means "done only": the measured-gap count is named apart
  assert.doesNotMatch(jobsSummaryText(s).replace(/finished \(done or failed\)/g, ""), /finished/);
});

test("same-title runs fold under the best attempt; running jobs and different states never fold", () => {
  const latch = "Cupboard turn-button latch — broken (synthetic, paper)";
  const list = [
    job("done", false, 4.32, { id: "a", title: latch }),
    job("done", true, 0.08, { id: "b", title: "Spacer" }),
    job("done", false, 8.57, { id: "c", title: latch }),
    job("running", false, null, { id: "d", title: latch }),
    job("done", false, 20.35, { id: "e", title: latch }),
    job("done", false, 0.5, { id: "f", title: latch, is_replay: true }),
  ];
  const g = groupJobAttempts(list);
  assert.deepEqual(g.map((x) => [x.lead.id, x.others.map((o) => o.id)]), [["a", ["c", "e"]], ["b", []], ["d", []], ["f", []]], "best first, list order kept; running and recorded runs keep their own row");
  assert.equal(g.reduce((n, x) => n + 1 + x.others.length, 0), list.length, "no run is dropped");
  // a verified attempt leads even when an unverified one has a smaller gap
  const v = groupJobAttempts([job("done", false, 0.2, { id: "x", title: "T" }), job("done", true, 0.4, { id: "y", title: "T" }), job("failed", false, null, { id: "z", title: "T" })]);
  assert.deepEqual([v[0].lead.id, v[0].others.map((o) => o.id)], ["y", ["x", "z"]]);
  assert.equal(moreAttemptsText(2), "+2 more attempts");
  assert.equal(moreAttemptsText(1), "+1 more attempt");
  const q = (job_id, status, gap, title = latch) => ({ job_id, title, status, verdict: { status: "best_effort", max_error_mm: gap } });
  const qg = groupQueueAttempts([q("1", "waiting", 8.57), q("2", "waiting", 4.32), q("3", "accepted", 0.1), q("4", "waiting", 20.35)]);
  assert.deepEqual(qg.map((x) => [x.lead.job_id, x.others.map((o) => o.job_id)]), [["2", ["1", "4"]], ["3", []]], "a waiting item never hides behind a decided one");
});

const fb = (id, root, round, over = {}) => ({ id, root_job: root, round, title: `Latch · review round ${round}`, family: "latch", by: "test", before_mm: null, after_mm: null, limit_mm: 0.5, at: round, ...over });

test("feedback groups into one block per part with its rounds in order", () => {
  const items = [
    fb("x3", "r1", 3, { before_mm: 0.4, after_mm: 0.3, at: 30 }),
    fb("y1", "r2", 1, { at: 50 }),
    fb("x1", "r1", 1, { before_mm: 0.9, at: 10 }),
    fb("x1b", "r1", 1, { after_mm: 0.6, at: 11 }),
  ];
  const blocks = groupFeedback(items);
  assert.deepEqual(blocks.map((b) => b.root), ["r2", "r1"], "newest activity first");
  const r1 = blocks[1];
  assert.equal(r1.title, "Latch");
  assert.deepEqual(r1.entries.map((e) => e.id), ["x1", "x1b", "x3"]);
  assert.deepEqual(r1.rounds, [
    { round: 1, before_mm: 0.9, after_mm: 0.6 },
    { round: 3, before_mm: 0.4, after_mm: 0.3 },
  ]);
  assert.equal(allTests(items), true);
  assert.equal(allTests([...items, fb("p", "r3", 1, { by: "person" })]), false);
  assert.equal(allTests([]), false);
});

test("feedback rounds prefer the verifier's verdicts over a pin's local gap", () => {
  const [b] = groupFeedback([
    fb("p1", "r", 1, { before_mm: 3.2, after_mm: 0.05, verdict: { max_error_mm: 3.68 }, next_verdict: { max_error_mm: 1.15 } }),
    fb("p2", "r", 1, { before_mm: 2.85, after_mm: 0.25, verdict: { max_error_mm: 3.68 }, next_verdict: { max_error_mm: 1.15 } }),
  ]);
  assert.deepEqual(b.rounds, [{ round: 1, before_mm: 3.68, after_mm: 1.15 }]);
});

test("a knob card whose runs moved the value both ways is conflicting evidence, not advice", () => {
  const run = (id, first, final) => ({ id, scope: "cover", rule: "r", status: "candidate", created_at: 0, evidence: { template: "battery_cover", param: "corner_radius", first, final }, links: [] });
  assert.deepEqual(lessonConflict([run("a", 1, 1.9), run("b", 2, 1.2), run("c", 1, 1.5)]), { up: 2, down: 1 });
  assert.equal(lessonConflict([run("a", 1, 1.9), run("c", 1, 1.5)]), null, "same direction agrees");
  assert.equal(lessonConflict([run("a", 1, 1.9)]), null);
});

test("builds using a card count each build once across its wordings", () => {
  assert.equal(buildsUsing([{ track: { used_in: 2, jobs: ["j1", "j2"] } }, { track: { used_in: 2, jobs: ["j2", "j3"] } }]), 3);
  assert.equal(buildsUsing([{ track: { used_in: 0, jobs: [] } }, { track: null }]), 0);
  assert.equal(buildsUsing([{ track: { used_in: 4 } }]), 4, "older API without ids");
});
