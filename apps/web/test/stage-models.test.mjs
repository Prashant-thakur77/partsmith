// Model tables on /models and /judges: how a stage runs now never shares a column with how its logged calls ran, and
// the models seen in model_call events (made here vs in recorded runs) show beside the configured one.
import assert from "node:assert/strict";
import test from "node:test";
import { MODE_WORD, sameModel, stageModelRows } from "../src/lib/stage-models.ts";

const prov = (stage, model, mode = "replay") => ({ stage, role: stage, provider: "meta", model, mode, key_env: null, key_present: false, open_weights: false, where: "Meta API", note: "" });
const call = (stage, model, mode, calls, usd = 0) => ({ stage, provider: "meta", model, mode, calls, failed: 0, tokens_in: 0, tokens_out: 0, usd, ms_mean: 1, open_weights: false });

test("a stage keeps its configured model and current mode, and lists every model its logged calls used", () => {
  const rows = stageModelRows({
    providers: [prov("judge", "muse-glimmer"), prov("build", "meta-models/muse-spark-open"), prov("narrate", "muse-spark-1.3")],
    model_calls: [call("judge", "muse-glimmer", "mock", 21), call("build", "meta-models/muse-spark-open-1026", "live", 33, 0.47)],
    model_calls_recorded: [call("judge", "muse-spark-1.3", "live", 3, 0.01)],
  });
  const judge = rows.find((r) => r.stage === "judge");
  assert.equal(judge.model, "muse-glimmer");
  assert.equal(MODE_WORD[judge.mode], "recorded", "runs now: recorded");
  assert.deepEqual(judge.seen.map((m) => [m.model, m.mode, m.calls, m.source]), [["muse-glimmer", "mock", 21, "here"], ["muse-spark-1.3", "live", 3, "recorded"]]);
  assert.equal(judge.differs, true);
  assert.equal(judge.usd, 0, "recorded runs are never spend here");
  const build = rows.find((r) => r.stage === "build");
  assert.equal(build.differs, false, "a dated model id is the same model");
  assert.equal(build.usd, 0.47);
  assert.deepEqual(rows.find((r) => r.stage === "narrate").seen, []);
  assert.equal(sameModel("muse-spark-1.3", "muse-spark-open"), false);
});
