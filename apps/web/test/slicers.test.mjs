// Unit tests for the "Open in slicer" hand-off and the export-gate link helpers (node --test; no browser, no network).
import assert from "node:assert/strict";
import test from "node:test";
import { exportLine, plainCheck, plainNote } from "../src/lib/bypass.ts";
import { PRINTABLE_KINDS, withAck } from "../src/lib/ship.ts";
import { SLICERS, absoluteUrl, slicerHandoff } from "../src/lib/slicers.ts";

const ORIGIN = "https://partsmith.example";
const BLOB = "/api/v1/blobs/" + "a".repeat(64) + ".3mf";

test("blocked parts show no slicer control at all", () => {
  assert.deepEqual(slicerHandoff(BLOB, ORIGIN, "blocked", true), { state: "hidden" });
  assert.deepEqual(slicerHandoff(undefined, ORIGIN, "verified", false), { state: "hidden" });
});

test("best effort waits for the same acknowledgement as downloads", () => {
  assert.deepEqual(slicerHandoff(BLOB, ORIGIN, "best_effort", false), { state: "needs_ack" });
  // acknowledged, but the link would still be refused by the server: not handed to a slicer
  assert.deepEqual(slicerHandoff(BLOB, ORIGIN, "best_effort", true), { state: "needs_ack" });
  const h = slicerHandoff(withAck(BLOB, true), ORIGIN, "best_effort", true);
  assert.equal(h.state, "ready");
  assert.equal(h.fileUrl, `${ORIGIN}${BLOB}?ack=1`);
});

test("verified parts get deep links that carry the absolute, encoded file URL", () => {
  const url = "/api/v1/parts/hook/bake?length=40&format=3mf&download=1";
  const h = slicerHandoff(url, ORIGIN, "verified", false);
  assert.equal(h.state, "ready");
  const abs = `${ORIGIN}${url}`;
  const byId = Object.fromEntries(h.links.map((l) => [l.slicer.id, l.href]));
  assert.equal(byId.bambu, `bambustudio://open?file=${encodeURIComponent(abs)}`);
  assert.equal(byId.orca, `orcaslicer://open?file=${encodeURIComponent(abs)}`);
  assert.equal(byId.prusa, null); // no web-URL scheme: download + instructions instead
  assert.match(SLICERS.find((s) => s.id === "prusa").howTo, /Download the 3MF/);
  // the encoded URL survives a round trip with its query intact
  assert.equal(decodeURIComponent(new URL(byId.bambu.replace("bambustudio:", "https:")).searchParams.get("file")), abs);
});

test("absoluteUrl keeps absolute URLs and resolves API paths against the site", () => {
  assert.equal(absoluteUrl("https://api.example/x.3mf", ORIGIN), "https://api.example/x.3mf");
  assert.equal(absoluteUrl("/api/v1/x.3mf", `${ORIGIN}/`), `${ORIGIN}/api/v1/x.3mf`);
});

test("withAck appends ack=1 only when acknowledged, before any fragment", () => {
  assert.equal(withAck("/a.stl", false), "/a.stl");
  assert.equal(withAck("/a.stl", true), "/a.stl?ack=1");
  assert.equal(withAck("/bake?format=stl#x", true), "/bake?format=stl&ack=1#x");
  assert.equal(withAck(undefined, true), undefined);
  for (const k of ["stl", "threemf", "step", "zip"]) assert.ok(PRINTABLE_KINDS.has(k));
  for (const k of ["coupon", "view", "code", "verification"]) assert.ok(!PRINTABLE_KINDS.has(k));
});

test("the caught-lie export line comes from the gate decision", () => {
  const blocked = exportLine({ export: { ok: false, requires_ack: false, status: "blocked", reason: "r" } });
  assert.deepEqual(blocked, { title: "Export blocked", sub: null });
  const held = exportLine({ export: { ok: false, requires_ack: true, status: "best_effort", reason: "r" } });
  assert.equal(held.title, "Export blocked");
  assert.match(held.sub, /acknowledg/);
  assert.equal(exportLine({ export: { ok: true, requires_ack: false, status: "verified", reason: "r" } }).title, "Export allowed");
});

test("lying-model report captions and check ids read in plain words", () => {
  assert.equal(plainNote("top view: the model built by the lying brain vs the photo silhouette"), "top view: the part the lying model built vs the photo silhouette");
  assert.equal(plainNote("top view: hatched = the end the brain claimed is broken off"), "top view: hatched = the end the model claimed is broken off");
  assert.deepEqual(["hole_1.diameter", "bbox.x", "residual_top"].map(plainCheck), ["hole 1 diameter", "overall length", "top outline"]);
});
