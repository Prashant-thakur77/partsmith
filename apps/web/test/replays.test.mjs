// Which stored runs are shown first (node --test; no browser). Picks come from the /replays list itself.
import assert from "node:assert/strict";
import test from "node:test";
import { curateReplays, replayTitle, replayVerdict } from "../src/lib/replays.ts";

const r = (id, title, verified, max_error_mm, iterations) => ({ id, title, origin: "synthetic", provider_mode: "live", verified, max_error_mm, iterations });

test("featured runs: a fixed verified run, the latest review round, a best-effort near miss", () => {
  const list = [
    r("a", "Hinge leaf (synthetic, clean)", false, 3.68, 6),
    r("b", "SD card (synthetic, clean)", true, 0.47, 1),
    r("c", "Battery cover (synthetic, clean)", true, 0.39, 3),
    r("d", "Hinge leaf (synthetic, clean) · review round 3", false, 0.38, 7),
    r("e", "Hinge leaf (synthetic, clean) · review round 4", true, 0.38, 2),
    r("f", "Knob (synthetic, clean)", false, 0.5, 6),
  ];
  const { featured, rest } = curateReplays(list);
  assert.deepEqual(featured.map((f) => f.replay.id), ["c", "e", "f"]);
  assert.equal(featured[0].why, "Verified after 3 rounds");
  assert.deepEqual(rest.map((x) => x.id), ["a", "b", "d"]);
  assert.deepEqual(curateReplays([]), { featured: [], rest: [] });
});

test("verdict words and titles", () => {
  assert.equal(replayVerdict({ verified: false, max_error_mm: 1.2 }), "best effort");
  assert.equal(replayVerdict({ verified: false, max_error_mm: null }), "no model");
  const split = (t) => ({ title: t.replace(/\s*\([^)]*\)\s*$/, "") });
  assert.equal(replayTitle("Hinge leaf (synthetic, clean) · review round 4", split), "Hinge leaf · review round 4");
});
