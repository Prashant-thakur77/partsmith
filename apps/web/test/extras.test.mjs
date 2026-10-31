// Unit tests for download file names (same rule as the API's Content-Disposition) and the /parts no-match banner
// (node --test; no browser, no network).
import assert from "node:assert/strict";
import test from "node:test";
import { downloadName, knobShort, MAX_LEN, numText, safe } from "../src/lib/download-name.ts";
import { matchBanner } from "../src/lib/search-match.ts";

test("download names match the API rule", () => {
  assert.equal(downloadName("cable-clip", ".stl"), "partsmith-cable-clip.stl");
  assert.equal(downloadName("cable-clip", "stl", { hole_d: 3.4, cable_d: 6 }, { hole_d: 3, cable_d: 6 }), "partsmith-cable-clip-hole3.4.stl");
  assert.equal(downloadName("desk-cable-clip", ".stl", { cable_d: 8 }, { cable_d: 6 }), "partsmith-desk-cable-clip-cable8.stl");
  assert.equal(downloadName("Weird Slug/../x", ".3mf", { channel_count: 3 }, { channel_count: 2 }), "partsmith-weird-slug-x-channelcount3.3mf");
  assert.equal(downloadName("spacer", ".stl", { height: 12 }, { height: 10 }, ["height"]), "partsmith-spacer-height12.stl");
  assert.equal(downloadName("cable-clip", ".view.json"), "partsmith-cable-clip.view.json");
});

test("long names stay within 80 safe ASCII characters", () => {
  const many = Object.fromEntries(Array.from({ length: 30 }, (_, i) => [`knob_${i}_mm`, i + 0.25]));
  const name = downloadName("a".repeat(40), ".step", many, {});
  assert.ok(name.length <= MAX_LEN, name);
  assert.ok(name.endsWith(".step") && name.includes("-plus"), name);
  assert.match(name, /^[a-z0-9.-]+$/);
  assert.ok(downloadName("x".repeat(120), ".stl").length <= MAX_LEN);
});

test("helpers", () => {
  assert.equal(numText(8), "8");
  assert.equal(numText(0.25), "0.25");
  assert.equal(numText(-5), "-5");
  assert.equal(numText(3.456), "3.46");
  assert.equal(knobShort("wall_t"), "wall");
  assert.equal(knobShort("hole_spacing"), "holespacing");
  assert.equal(safe("Cable_Clip v2!"), "cable-clip-v2");
});

test("no-match banner only for a query that matched partly or not at all", () => {
  assert.equal(matchBanner("good", 1, null, "cable clip"), null);
  assert.equal(matchBanner("all", null, null, ""), null);
  assert.equal(matchBanner("none", 0, "No close match", ""), null);
  assert.equal(matchBanner(undefined, undefined, undefined, "x"), null); // older backend: no fields, no banner
  const none = matchBanner("none", 0, "No close match — describe it", " zeppelin ");
  assert.deepEqual(none, { tone: "warn", title: "No close match for “zeppelin”", hint: "No close match — describe it", coveragePct: 0 });
  const partial = matchBanner("partial", 0.667, "Only a partial match", "cable clip 400 mm");
  assert.equal(partial?.tone, "neutral");
  assert.equal(partial?.coveragePct, 67);
});

test("comparison table: categories only, qualitative cells, one cell per column", async () => {
  const { COMPARE_COLUMNS, COMPARE_ROWS, cellText } = await import("../src/lib/compare.ts");
  assert.equal(COMPARE_COLUMNS.length, 5);
  assert.equal(COMPARE_COLUMNS.at(-1), "PartSmith");
  for (const row of COMPARE_ROWS) {
    assert.equal(row.cells.length, COMPARE_COLUMNS.length, row.feature);
    for (const c of row.cells) {
      assert.ok(["yes", "no", "partial", "text"].includes(c.mark));
      if (c.mark !== "text") assert.equal(c.label, { yes: "Yes", no: "No", partial: "Partial" }[c.mark]);
      // qualitative only: no measured numbers or percentages in any cell
      assert.doesNotMatch(`${c.label} ${c.note ?? ""}`, /\d/);
    }
  }
  const words = JSON.stringify(COMPARE_ROWS) + COMPARE_COLUMNS.join(" ");
  // every capitalised word is a plain English word or one of ours: no product or company names slip in
  const allowed = new Set(["Text", "CAD", "Photo", "Phone", "Model", "PartSmith", "Yes", "No", "Partial", "Usually", "Varies", "Free", "REST", "MCP", "CadQuery", "Real", "Editable", "Pass", "Learns", "Fit", "Agent", "Cost", "API"]);
  for (const w of words.match(/\b[A-Z][A-Za-z]+\b/g) ?? []) assert.ok(allowed.has(w), `unexpected name-like word: ${w}`);
  assert.equal(cellText("PartSmith", { mark: "yes", label: "Yes", note: "n" }), "PartSmith: Yes — n");
  const ours = COMPARE_ROWS.filter((r) => r.feature !== "Cost to use").map((r) => r.cells.at(-1).mark);
  assert.ok(ours.every((m) => m === "yes"));
});

test("job cost adds up the job's own model_call events", async () => {
  const { jobCost } = await import("../src/lib/job-cost.ts");
  const call = (model, mode, usd, tin, tout, ok = true) => ({ provider: "p", model, stage: "build", mode, tokens_in: tin, tokens_out: tout, usd, ok });
  const live = jobCost([call("a", "live", 0.002, 100, 50), call("b", "live", 0.001, 10, 5), call("a", "live", 0.003, 200, 70, false)], { replay: false });
  assert.equal(live.kind, "live");
  assert.equal(live.calls, 3);
  assert.equal(live.failed, 1);
  assert.equal(live.tokensIn, 310);
  assert.equal(live.tokensOut, 125);
  assert.ok(Math.abs(live.usd - 0.006) < 1e-12);
  assert.deepEqual(live.perModel.map((m) => [m.model, m.calls]), [["a", 2], ["b", 1]]);
  const mock = jobCost([call("a", "mock", 0, 0, 0)], { replay: false });
  assert.equal(mock.kind, "mock");
  assert.equal(mock.note, "mock — no spend");
  const replay = jobCost([call("a", "live", 0.01, 1, 1)], { replay: true });
  assert.equal(replay.kind, "replay");
  assert.match(replay.note, /^recorded cost of the original run/);
  assert.match(jobCost([call("a", "mock", 0, 0, 0)], { replay: true }).note, /no spend/);
  assert.equal(jobCost([], { replay: false }).calls, 0);
  assert.match(jobCost([call("a", "live", 0.01, 1, 1), call("b", "mock", 0, 0, 0)], { replay: false }).note, /1 of 2 calls/);
});

test("load notes: load-bearing families only, always with the safety warning", async () => {
  const { LOAD_RULES, SAFETY_WARNING, loadNote } = await import("../src/lib/load-notes.ts");
  for (const f of ["hinge", "bracket", "latch", "clip", "hook"]) {
    const n = loadNote(f);
    assert.ok(n, f);
    assert.equal(n.warning, SAFETY_WARNING);
    assert.match(n.material, /PETG/);
    assert.ok(n.orientation.length > 20 && n.walls.length > 5);
  }
  assert.match(SAFETY_WARNING, /^Not for safety-critical loads/);
  for (const f of ["knob", "spacer", "cover", "wheel", "custom", "", null, undefined]) assert.equal(loadNote(f), null);
  assert.deepEqual(Object.keys(LOAD_RULES).sort(), ["bracket", "clip", "hinge", "hook", "latch"]);
});

test("hidden sizes from the /fix form: blank rows dropped, bad numbers named, other needs a name", async () => {
  const { HIDDEN_KINDS, MAX_HIDDEN, hiddenDimsPayload, hiddenStatusText } = await import("../src/lib/hidden-dims.ts");
  assert.deepEqual(HIDDEN_KINDS.map((k) => k.name), ["bore_d", "socket_depth", "hole_d", "wall", "cable_d"]);
  const { dims, problems } = hiddenDimsPayload([
    { kind: "bore_d", other: "", value: "8" },
    { kind: "socket_depth", other: "", value: "" }, // blank: ignored
    { kind: "wall", other: "", value: "2,5" },
    { kind: "other", other: "lip depth", value: "1.25" },
  ]);
  assert.deepEqual(dims, [{ name: "bore_d", value_mm: 8 }, { name: "wall", value_mm: 2.5 }, { name: "lip depth", value_mm: 1.25 }]);
  assert.deepEqual(problems, {});
  const bad = hiddenDimsPayload([{ kind: "bore_d", other: "", value: "-3" }, { kind: "other", other: "", value: "4" }, { kind: "other", other: "lip", value: "" }]);
  assert.deepEqual(bad.dims, []);
  assert.deepEqual(Object.keys(bad.problems), ["0", "1", "2"]);
  assert.equal(hiddenDimsPayload(Array.from({ length: 6 }, () => ({ kind: "wall", other: "", value: "2" }))).dims.length, MAX_HIDDEN);
  assert.equal(hiddenStatusText("used_not_checked"), "used, not checked from the photo");
  assert.equal(hiddenStatusText("pending"), "checked once the verdict is in");
});

test("run modes come from the run's own model_call events: a live run with a mock judge is mixed", async () => {
  const { runModes, runModesText } = await import("../src/lib/job-cost.ts");
  const m = runModes([{ mode: "live" }, { mode: "live" }, { mode: "mock" }]);
  assert.equal(m.mode, "mixed");
  assert.equal(runModesText(m), "2 live · 1 mock calls");
  assert.equal(runModes([{ mode: "replay" }]).mode, "replay");
  assert.equal(runModes([]), null);
});
