// Unit tests for the repair passport helpers (node --test; no browser, no network).
import assert from "node:assert/strict";
import test from "node:test";
import { PASSPORT_LEN, fixPrefill, groupPassportId, normalizePassportId, passportLink, qrFileName, reprintOpen, reprintUrl } from "../src/lib/passport.ts";

test("ids are read the way people type them, like the server's normalize", () => {
  assert.equal(normalizePassportId("7kq-3mz"), "7KQ3MZ");
  assert.equal(normalizePassportId(" 7KQ 3MZ "), "7KQ3MZ");
  assert.equal(normalizePassportId("O1L2I3"), "011213");
  assert.equal(normalizePassportId("ABCDU1"), null); // U is not in Crockford base32
  assert.equal(normalizePassportId("ABC"), null);
  assert.equal(normalizePassportId("ABCDEFG"), null);
  assert.equal(PASSPORT_LEN, 6);
  assert.equal(groupPassportId("7KQ3MZ"), "7KQ 3MZ");
});

test("the reprint link keeps the passport's bake route and adds only download options", () => {
  const u = reprintUrl("/api/v1/parts/latch-52mm/bake", { format: "3mf", preset: "petg-fdm-0.4", fitSession: "d-abcdefgh12", ack: false, mark: true });
  const [path, query] = u.split("?");
  assert.equal(path, "/api/v1/parts/latch-52mm/bake");
  const qs = new URLSearchParams(query);
  assert.deepEqual(Object.fromEntries(qs), { format: "3mf", preset: "petg-fdm-0.4", fit_session: "d-abcdefgh12", download: "1", passport: "1" });
  const acked = new URLSearchParams(reprintUrl("/api/v1/jobs/j_1/bake", { format: "stl", ack: true }).split("?")[1]);
  assert.equal(acked.get("ack"), "1");
  assert.equal(acked.get("passport"), null);
  assert.equal(acked.get("preset"), null);
});

test("the gate mirrors the server: verified opens, best effort needs the acknowledgement, blocked never", () => {
  assert.equal(reprintOpen("verified", false), true);
  assert.equal(reprintOpen("best_effort", false), false);
  assert.equal(reprintOpen("best_effort", true), true);
  assert.equal(reprintOpen("blocked", true), false);
});

test("/fix prefill accepts known families only and caps the intent", () => {
  const fams = ["latch", "clip"];
  assert.deepEqual(fixPrefill("?family=latch&intent=Replacement%20for%20latch", fams), { family: "latch", intent: "Replacement for latch" });
  assert.deepEqual(fixPrefill("family=rocket&intent=x", fams), { family: "", intent: "x" });
  assert.equal(fixPrefill(`?intent=${"a".repeat(900)}`, fams).intent.length, 500);
  assert.deepEqual(fixPrefill("", fams), { family: "", intent: "" });
});

test("links and file names", () => {
  assert.equal(passportLink("https://partsmith.example/", "7KQ3MZ"), "https://partsmith.example/p/7KQ3MZ");
  assert.equal(qrFileName("7KQ3MZ", "svg"), "partsmith-passport-7KQ3MZ.svg");
});
