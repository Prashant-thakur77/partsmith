// Unit tests for the live voice PCM/frame helpers and the server-message guard (node --test; no browser, no network).
import assert from "node:assert/strict";
import test from "node:test";
import {
  Downsampler,
  FRAME_SAMPLES,
  FrameChunker,
  closedReasonText,
  floatToPcm16,
  parseVoiceMessage,
  pcm16Bytes,
  rmsLevel,
  voiceSocketUrl,
} from "../src/lib/live-voice.ts";

const tone = (n, rate, hz, amp = 0.5) => Float32Array.from({ length: n }, (_, i) => amp * Math.sin((2 * Math.PI * hz * i) / rate));

test("48 kHz → 16 kHz keeps the length ratio across uneven chunks and averages each 3-sample window", () => {
  const d = new Downsampler(48000);
  const input = Float32Array.from({ length: 4800 }, (_, i) => i % 3); // 0,1,2 repeating → every window averages to 1
  let total = 0;
  for (const size of [128, 1000, 7, 2048, 1617]) {
    total += d.push(input.subarray(0, size)).length;
  }
  assert.equal(total, Math.floor((128 + 1000 + 7 + 2048 + 1617) / 3));
  const steady = new Downsampler(48000).push(input);
  assert.equal(steady.length, 1600);
  assert.ok(steady.every((v) => Math.abs(v - 1) < 1e-6));
});

test("44.1 kHz → 16 kHz: fractional ratio, total samples within one of the exact count, no clicks at chunk joins", () => {
  const rate = 44100;
  const sig = tone(rate, rate, 440);
  const d = new Downsampler(rate);
  const parts = [];
  for (let i = 0; i < sig.length; i += 1000) parts.push(d.push(sig.subarray(i, i + 1000)));
  const out = Float32Array.from(parts.flatMap((p) => Array.from(p)));
  assert.ok(Math.abs(out.length - 16000) <= 1, `got ${out.length}`);
  const whole = new Downsampler(rate).push(sig);
  assert.deepEqual(Array.from(out), Array.from(whole).slice(0, out.length)); // chunking does not change a sample
});

test("16 kHz passes through unchanged; rates below 16 kHz are refused", () => {
  const sig = tone(320, 16000, 1000);
  assert.deepEqual(Array.from(new Downsampler(16000).push(sig)), Array.from(sig));
  assert.throws(() => new Downsampler(8000), RangeError);
});

test("float → PCM16 clamps and maps the full scale", () => {
  assert.deepEqual(Array.from(floatToPcm16(Float32Array.from([0, 1, -1, 2, -2, 0.5, NaN]))), [0, 32767, -32768, 32767, -32768, 16384, 0]);
});

test("frames are 100 ms (1600 samples); the remainder is flushed once", () => {
  const c = new FrameChunker();
  assert.equal(c.push(new Int16Array(1000)).length, 0);
  const frames = c.push(Int16Array.from({ length: 2500 }, (_, i) => i));
  assert.equal(frames.length, 2);
  assert.ok(frames.every((f) => f.length === FRAME_SAMPLES));
  assert.equal(frames[0][1000], 0);
  assert.equal(frames[1][0], 600);
  assert.equal(c.flush()?.length, 300);
  assert.equal(c.flush(), null);
});

test("PCM bytes are little-endian s16 (what the server expects)", () => {
  const b = new Uint8Array(pcm16Bytes(Int16Array.from([1, -2, 0x1234])));
  assert.deepEqual(Array.from(b), [1, 0, 0xfe, 0xff, 0x34, 0x12]);
  assert.equal(new Uint8Array(pcm16Bytes(new Int16Array(FRAME_SAMPLES))).length, 3200);
});

test("level meter", () => {
  assert.equal(rmsLevel(new Float32Array(0)), 0);
  assert.ok(Math.abs(rmsLevel(Float32Array.from([0.5, -0.5])) - 0.5) < 1e-9);
});

test("socket URL: same origin by default, or the configured API host", () => {
  assert.equal(voiceSocketUrl("j_1", { protocol: "https:", host: "partsmith.example" }), "wss://partsmith.example/api/v1/jobs/j_1/voice/live");
  assert.equal(voiceSocketUrl("j 1", { protocol: "http:", host: "localhost:3000" }), "ws://localhost:3000/api/v1/jobs/j%201/voice/live");
  assert.equal(voiceSocketUrl("j", { protocol: "https:", host: "w" }, "https://api.example/"), "wss://api.example/api/v1/jobs/j/voice/live");
  assert.equal(voiceSocketUrl("j", { protocol: "https:", host: "w" }, "ws://127.0.0.1:8000"), "ws://127.0.0.1:8000/api/v1/jobs/j/voice/live");
  assert.equal(voiceSocketUrl("j", { protocol: "https:", host: "w" }, "ftp://nope"), "wss://w/api/v1/jobs/j/voice/live");
});

test("server messages: valid ones parse, malformed ones are ignored", () => {
  const ready = parseVoiceMessage(JSON.stringify({ type: "ready", mode: "mock", model: "m", keywords: ["Hook", 3], sample_rate: 16000, max_seconds: 60, max_bytes: 9, mock_script: "hook ko 1 mm mota karo" }));
  assert.equal(ready?.type, "ready");
  assert.deepEqual(ready.keywords, ["Hook"]);
  assert.deepEqual(parseVoiceMessage(JSON.stringify({ type: "partial", text: "hook ko", turn_id: "1", mode: "mock" })), { type: "partial", text: "hook ko", turn_id: "1", mode: "mock" });
  const edit = parseVoiceMessage(JSON.stringify({ type: "edit", turn_id: null, result: { transcript: "x", edits: [{ param: "a", from: 1, to: 2 }], confidence: 0.9, mode: "mock" } }));
  assert.equal(edit?.type === "edit" && edit.result.edits[0].to, 2);
  assert.deepEqual(parseVoiceMessage(JSON.stringify({ type: "capped", reason: "time", limit: 60 })), { type: "capped", reason: "time", limit: 60 });
  assert.equal(parseVoiceMessage(JSON.stringify({ type: "closed", reason: "time_cap" }))?.finals, 0);
  for (const bad of ["nope", "{}", "[]", JSON.stringify({ type: "partial" }), JSON.stringify({ type: "edit", result: {} }), JSON.stringify({ type: "capped", reason: "x", limit: 1 }), new ArrayBuffer(2)]) {
    assert.equal(parseVoiceMessage(bad), null, String(bad));
  }
  assert.match(closedReasonText("time_cap", 60), /60 s/);
});
