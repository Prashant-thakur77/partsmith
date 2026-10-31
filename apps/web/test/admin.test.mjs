// Unit tests for the admin console contract and helpers (node --test; no browser, no network).
import assert from "node:assert/strict";
import test from "node:test";
import {
  AdminOverviewSchema,
  AdminPartsSchema,
  AuditLogSchema,
  DemandSchema,
  TaughtRulesSchema,
  budgetBar,
  changeText,
  criteriaLine,
  criterionValue,
  path,
  pct,
  ruleTrack,
  shares,
  tabFromParam,
} from "../src/lib/api-admin.ts";

const src = "test";
const overview = {
  generated_at: 1,
  mode: "mock",
  jobs: { total: 3, finished: 3, verified: 2, pass_rate: 0.6667, n: 3, replays_excluded: 1, source: src },
  rounds_to_verify: { buckets: [{ rounds: 1, count: 1 }], median: 1, n: 1, source: src },
  max_error: { median_mm: 0.4, p90_mm: 0.9, n: 3, source: src },
  send_back: { person: { n: 1, top: [{ reason: "Wrong hole", count: 1 }] }, test: { n: 0, top: [] }, source: src },
  review: { waiting: 2, improving: 0, accepted: 0, rejected: 1, waiting_replays: 0, n: 3, source: src },
  registry: { published: 2, withdrawn: 0, reference: 0, n: 2, source: src },
  needs: { open: 1, in_progress: 0, fulfilled: 0, n: 1, source: src },
  cost: { usd_total: 0.06, usd_per_job_mean: 0.02, n_jobs: 3, by_stage: [{ stage: "build", calls: 3, usd: 0.06 }], by_model: [], source: src },
  budget: { day: "2026-10-31", cap_usd: 5, spent_usd: 1.25, remaining_usd: 3.75, calls: 4, by_stage: {}, source: src },
};

test("the overview schema accepts the API's shape and tolerates a server without a budget block", () => {
  assert.equal(AdminOverviewSchema.parse(overview).jobs.pass_rate, 0.6667);
  const { budget: _b, ...old } = overview;
  assert.ok(AdminOverviewSchema.parse(old).budget == null);
  assert.equal(AdminOverviewSchema.parse({ ...overview, budget: { nonsense: true } }).budget, null);
  assert.equal(AdminOverviewSchema.safeParse({ ...overview, jobs: { total: "3" } }).success, false);
});

test("budget bar: share of the cap, no cap, cap reached", () => {
  assert.deepEqual(budgetBar(overview.budget), { share: 0.25, label: "$1.25 of $5.00 spent today (2026-10-31 UTC).", over: false });
  const none = budgetBar({ ...overview.budget, cap_usd: null, remaining_usd: null });
  assert.equal(none.share, null);
  assert.match(none.label, /^No cap set\. Spent \$1\.25 today/);
  const over = budgetBar({ ...overview.budget, spent_usd: 6 });
  assert.equal(over.share, 1);
  assert.equal(over.over, true);
  assert.match(over.label, /paused/);
  assert.match(budgetBar(null).label, /does not report/);
});

test("tabs come from ?tab= with Overview as the fallback", () => {
  assert.equal(tabFromParam("rules"), "rules");
  assert.equal(tabFromParam("nope"), "overview");
  assert.equal(tabFromParam(null), "overview");
});

test("bar shares are relative to the largest value", () => {
  assert.deepEqual(shares([2, 4, 0]), [0.5, 1, 0]);
  assert.deepEqual(shares([0, 0]), [0, 0]);
  assert.deepEqual(shares([]), []);
});

test("criteria text reads numbers straight from the response", () => {
  const parts = AdminPartsSchema.parse({
    items: [
      {
        slug: "s-one",
        title: "Spacer",
        family: "spacer",
        status: "verified",
        criteria: [
          { key: "verified", label: "Verified by code", ok: true, value: "verified", source: src },
          { key: "max_error", label: "Max error within the limit", ok: true, value: { max_error_mm: 0.12, limit_mm: 0.5 }, source: src },
          { key: "accepted_by_person", label: "Accepted by a person", ok: false, value: null, source: src },
          { key: "x", label: "Unknown", ok: null, value: { other: 1 }, source: src },
        ],
        met: 2,
        checked: 3,
        withdrawn: { reason: "duplicate", by: "admin token", at: 1 },
      },
    ],
    n: 1,
    withdrawn: 1,
    source: src,
  });
  const [p] = parts.items;
  assert.equal(criteriaLine(p), "2 of 3 checks met");
  assert.equal(criteriaLine({ met: 1, checked: 1 }), "1 of 1 check met");
  assert.equal(criterionValue(p.criteria[1]), "0.12 mm (limit 0.50 mm)");
  assert.equal(criterionValue(p.criteria[2]), "—");
  assert.equal(criterionValue(p.criteria[3]), "—");
  assert.equal(p.withdrawn.reason, "duplicate");
});

test("rule track text and rule ids with slashes in paths", () => {
  const rules = TaughtRulesSchema.parse({
    items: [{ id: "r/1/pin1", kind: "feedback", family: "spacer", text: "t", used_in: ["j1"], track: { used_in: 1, accepted: 1, improved: 0, rejected: 0 } }],
    n: 1,
    disabled: 0,
    source: src,
  });
  assert.equal(ruleTrack(rules.items[0]), "Given to 1 job; later reviews: 1 accepted, 0 sent back, 0 rejected.");
  assert.equal(ruleTrack({ track: { used_in: 0, accepted: 0, improved: 0, rejected: 0 } }), null);
  assert.equal(path("/admin/rules/{rule_id}/disable", "rule_id", "r/1/pin1"), "/admin/rules/r%2F1%2Fpin1/disable");
});

test("audit and demand shapes; change text", () => {
  const log = AuditLogSchema.parse({ items: [{ id: "a1", at: 1, action: "part.unpublish", target: "s", actor: "admin token", before: { withdrawn: null }, after: { withdrawn: { reason: "dup" } }, note: "dup", numbers: null }], total: 1, actions: ["part.unpublish"], source: src });
  assert.equal(changeText(log.items[0].before), "withdrawn: none");
  assert.equal(changeText(log.items[0].after), 'withdrawn: "dup"');
  assert.equal(changeText({ status: "open" }), "status: open");
  assert.equal(changeText(null), "—");
  const d = DemandSchema.parse({ needs: [], missed_searches: [{ q: "wheel 22 mm", count: 3, best_coverage: { odd: 1 }, last_at: null }] });
  assert.equal(d.missed_searches[0].best_coverage, null);
  assert.equal(pct(0.6667), "66.7%");
  assert.equal(pct(null), "—");
});
