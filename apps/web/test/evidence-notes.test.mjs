// Unit tests for the evidence wording helpers and tolerant schemas: unchecked knobs, photo bounds, narration, voice note
// (node --test; no browser, no network).
import assert from "node:assert/strict";
import test from "node:test";
import { MeasuredSchema, NarrationRecordSchema, VerificationSchema } from "../src/lib/api-types.ts";
import {
  NARRATION_NOTE,
  audioTypeFromName,
  boundText,
  isNarrated,
  measuredValuesText,
  narrationView,
  uncheckedReason,
  uploadRefusal,
  voiceNoteName,
  voiceNoteProblem,
} from "../src/lib/evidence-notes.ts";

const SERVER_NOTE =
  "not measured: from the program (template default or inferred from the measured values); no test compares it with the photo, which covers it only as far as it changes the compared silhouettes (top)";

test("an unchecked knob's reason is the short cause from the server's note", () => {
  assert.equal(uncheckedReason(SERVER_NOTE), "template default or inferred from the measured values");
  assert.equal(uncheckedReason("template default"), "template default");
  assert.ok(uncheckedReason("x".repeat(200)).length <= 90);
});

test("the photo bound is worded low to high, and junk shows nothing", () => {
  assert.equal(boundText([41.2, 42]), "photo allows 41.20–42.00 mm");
  assert.equal(boundText([42, 41.2]), "photo allows 41.20–42.00 mm");
  assert.equal(boundText(null), null);
  assert.equal(boundText(undefined), null);
  assert.equal(boundText([Number.NaN, 2]), null);
});

test("values from narrated points are recognised by the server's evidence note", () => {
  assert.equal(isNarrated(`sam point prompt; ${NARRATION_NOTE}`), true);
  assert.equal(isNarrated("tap prompt"), false);
  assert.equal(isNarrated(null), false);
});

test("schemas: unchecked and bound_mm are tolerant", () => {
  const v = VerificationSchema.parse({
    verified: true,
    status: "verified",
    unchecked: [{ param: "latch_height", value: 3.5, note: SERVER_NOTE }, { param: 3 }, "x"],
  });
  assert.equal(v.unchecked.length, 1);
  assert.equal(v.unchecked[0].source, "inferred");
  assert.equal(v.unchecked[0].unit, "mm");
  assert.deepEqual(VerificationSchema.parse({ verified: false, status: "best_effort", unchecked: "bad" }).unchecked, []);
  assert.deepEqual(MeasuredSchema.parse({ value: 41.2, bound_mm: [41.2, 42] }).bound_mm, [41.2, 42]);
  assert.equal(MeasuredSchema.parse({ value: 41.2, bound_mm: ["a"] }).bound_mm, null);
});

const RECORD = {
  narration: {
    function: "holds the battery lid shut",
    mating_feature: "",
    break_description: "the latch tab snapped at the root",
    features: [],
    notes: [],
    transcript: "ye latch hai, yahan se toota",
    mode: "mock",
    label: "MOCK — no model watched the clip",
  },
  points: [
    { name: "hole_1", kind: "hole", t_s: 2.5, x_px: 300, y_px: 200, said: "ye hole", ok: true, reason: "", frame_index: 60, mat_mm: [10, 12] },
    { name: "tab", kind: "tab", t_s: 4, x_px: 5000, y_px: 9, said: "", ok: false, reason: "pixel (5000, 9) is outside the 1280 x 720 frame", frame_index: 96, mat_mm: null },
    { name: 7, ok: "maybe" },
  ],
  measured: [
    { id: "hole_1", kind: "hole", ok: true, method: "sam", center_mat_mm: [10, 12], values_mm: { diameter: 4.2 }, reason: "", provenance: NARRATION_NOTE },
    { id: "slot_x", kind: "slot", ok: false, method: "sam", values_mm: {}, reason: "mask too small", provenance: NARRATION_NOTE },
  ],
  merged: [],
  same_placement: false,
};

test("narration: summary steers, kept points carry their measurement, dropped points keep their reason", () => {
  const rec = NarrationRecordSchema.parse(RECORD);
  assert.equal(rec.points.length, 2, "a malformed point is dropped, not shown half-parsed");
  const v = narrationView(rec);
  assert.deepEqual(
    v.summary.map((s) => s.label),
    ["What it does", "The break"],
  );
  assert.equal(v.kept.length, 1);
  assert.equal(v.kept[0].measured?.values_mm.diameter, 4.2);
  assert.deepEqual(
    v.dropped.map((p) => [p.name, p.reason]),
    [["tab", "pixel (5000, 9) is outside the 1280 x 720 frame"]],
  );
  assert.deepEqual(v.otherMeasured.map((m) => m.id), ["slot_x"]);
  assert.equal(measuredValuesText({ diameter: 4.2, hole_depth: 3 }), "diameter 4.20 mm, hole depth 3.00 mm");
  assert.equal(rec.same_placement, false);
});

test("narration: a record with a broken summary still lists its points", () => {
  const rec = NarrationRecordSchema.parse({ ...RECORD, narration: "oops" });
  assert.equal(rec.narration.mode, "mock");
  assert.equal(narrationView(rec).summary.length, 0);
  assert.equal(narrationView(rec).kept.length, 1);
});

test("voice note: same size and type rule as the server, sensible names and types", () => {
  assert.equal(voiceNoteProblem("audio/webm;codecs=opus", 120_000), null);
  assert.equal(voiceNoteProblem("audio/mp4", 2_000_000), null);
  assert.equal(voiceNoteProblem("", 1000), null, "an untyped file is left to the server");
  assert.match(voiceNoteProblem("audio/webm", 16 * 1024 * 1024), /15 MB/);
  assert.match(voiceNoteProblem("image/png", 1000), /not an accepted audio type/);
  assert.match(voiceNoteProblem("audio/wav", 0), /empty/);
  assert.equal(voiceNoteName("audio/webm;codecs=opus"), "voice-note.webm");
  assert.equal(voiceNoteName("audio/mp4"), "voice-note.m4a");
  assert.equal(voiceNoteName("audio/ogg"), "voice-note.ogg");
  assert.equal(audioTypeFromName("note.M4A"), "audio/mp4");
  assert.equal(audioTypeFromName("note.txt"), null);
  assert.equal(audioTypeFromName("noext"), null);
});

test("413 and 415 refusals name the upload the server refused", () => {
  assert.match(uploadRefusal(413, "narration: 16.0 MB > 15 MB limit"), /^The voice note is too large/);
  assert.match(uploadRefusal(415, "orbit: use an MP4, MOV or WebM clip"), /^The walk-around clip is in a format/);
  assert.match(uploadRefusal(415, "side: not an image"), /^The side photo/);
  assert.equal(uploadRefusal(422, "x"), null);
});
