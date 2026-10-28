/**
 * Live voice helpers (pure): microphone Float32 audio at the device rate → 16 kHz mono PCM s16le frames for the
 * `/api/v1/jobs/{id}/voice/live` WebSocket, the socket URL, and a guard for the server's JSON messages.
 *
 * Kept free of runtime imports so `node --test` can load it directly.
 */

export const TARGET_RATE = 16_000;
/** 100 ms of 16 kHz audio per WebSocket frame (3200 bytes). */
export const FRAME_SAMPLES = 1600;

/**
 * Streaming box-filter downsampler: output sample k is the mean of input samples [⌊k·from/to⌋, ⌊(k+1)·from/to⌋), so
 * content above 8 kHz is attenuated instead of folding back. Positions are integers on the absolute sample clock, so
 * the output does not depend on how the input was chunked (no clicks at chunk joins). Rates below the target are
 * refused (the caller falls back to the file path).
 */
export class Downsampler {
  readonly fromRate: number;
  readonly toRate: number;
  private tail: Float32Array = new Float32Array(0);
  private tailStart = 0; // absolute input index of tail[0]
  private k = 0; // next output index

  constructor(fromRate: number, toRate: number = TARGET_RATE) {
    const from = Math.round(fromRate);
    const to = Math.round(toRate);
    if (!(to > 0) || !(from >= to)) throw new RangeError(`cannot resample ${fromRate} Hz to ${toRate} Hz`);
    this.fromRate = from;
    this.toRate = to;
  }

  private edge(k: number): number {
    return Math.floor((k * this.fromRate) / this.toRate);
  }

  push(input: Float32Array): Float32Array {
    const buf = new Float32Array(this.tail.length + input.length);
    buf.set(this.tail, 0);
    buf.set(input, this.tail.length);
    const bufEnd = this.tailStart + buf.length;
    const out: number[] = [];
    for (;;) {
      const start = this.edge(this.k);
      const end = Math.max(start + 1, this.edge(this.k + 1));
      if (end > bufEnd) break;
      let sum = 0;
      for (let i = start; i < end; i++) sum += buf[i - this.tailStart] ?? 0;
      out.push(sum / (end - start));
      this.k++;
    }
    const next = Math.min(this.edge(this.k), bufEnd);
    this.tail = buf.slice(next - this.tailStart);
    this.tailStart = next;
    return Float32Array.from(out);
  }
}

/** Float samples in [-1, 1] → signed 16-bit (clamped). */
export function floatToPcm16(input: Float32Array): Int16Array {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const v = input[i] ?? 0;
    const s = Math.max(-1, Math.min(1, Number.isFinite(v) ? v : 0));
    out[i] = s < 0 ? Math.round(s * 0x8000) : Math.round(s * 0x7fff);
  }
  return out;
}

/** Collects samples and hands out fixed-size frames; `flush()` returns the remainder (or null). */
export class FrameChunker {
  readonly size: number;
  private buf: Int16Array;
  private len = 0;

  constructor(size: number = FRAME_SAMPLES) {
    if (!(size > 0)) throw new RangeError("frame size must be positive");
    this.size = size;
    this.buf = new Int16Array(size);
  }

  push(samples: Int16Array): Int16Array[] {
    const frames: Int16Array[] = [];
    let i = 0;
    while (i < samples.length) {
      const take = Math.min(this.size - this.len, samples.length - i);
      this.buf.set(samples.subarray(i, i + take), this.len);
      this.len += take;
      i += take;
      if (this.len === this.size) {
        frames.push(this.buf);
        this.buf = new Int16Array(this.size);
        this.len = 0;
      }
    }
    return frames;
  }

  flush(): Int16Array | null {
    if (!this.len) return null;
    const out = this.buf.slice(0, this.len);
    this.len = 0;
    return out;
  }
}

/** Little-endian bytes of the samples (what the server expects: PCM s16le). */
export function pcm16Bytes(samples: Int16Array): ArrayBuffer {
  const out = new ArrayBuffer(samples.length * 2);
  const view = new DataView(out);
  for (let i = 0; i < samples.length; i++) view.setInt16(i * 2, samples[i] ?? 0, true);
  return out;
}

/** Root-mean-square level in [0, 1] for the recording meter. */
export function rmsLevel(input: Float32Array): number {
  if (!input.length) return 0;
  let sum = 0;
  for (const v of input) sum += v * v;
  return Math.min(1, Math.sqrt(sum / input.length));
}

/**
 * WebSocket URL of a job's live voice session. `override` (NEXT_PUBLIC_VOICE_WS_ORIGIN) points at the API host
 * when the web host cannot proxy WebSockets; otherwise the same origin is used (the web server proxies `/api/v1`).
 */
export function voiceSocketUrl(jobId: string, page: { protocol: string; host: string }, override?: string | null): string {
  const path = `/api/v1/jobs/${encodeURIComponent(jobId)}/voice/live`;
  const o = (override ?? "").trim().replace(/\/+$/, "");
  if (o) {
    const ws = o.replace(/^http(s?):\/\//i, (_m, s: string) => (s ? "wss://" : "ws://"));
    if (/^wss?:\/\//i.test(ws)) return ws + path;
  }
  return `${page.protocol === "https:" ? "wss" : "ws"}://${page.host}${path}`;
}

export type LiveEditResult = {
  transcript: string;
  edits: { param: string; from: number; to: number; reason?: string }[];
  not_understood?: string[];
  confidence: number;
  mode: string;
  transcript_mode?: string;
  bake?: unknown;
};

export type VoiceServerMessage =
  | {
      type: "ready";
      mode: string;
      model: string;
      keywords: string[];
      sample_rate: number;
      max_seconds: number;
      max_bytes: number;
      mock_script?: string;
      note?: string;
    }
  | { type: "speech_start" | "speech_end"; turn_id: string | null; mode: string }
  | { type: "partial" | "final"; text: string; turn_id: string | null; mode: string }
  | { type: "edit"; turn_id: string | null; result: LiveEditResult }
  | { type: "edit_error"; turn_id: string | null; code: string; message: string }
  | { type: "capped"; reason: "time" | "size"; limit: number }
  | { type: "warning" | "error"; code: string; message: string }
  | { type: "pong" }
  | { type: "closed"; reason: string; seconds: number; bytes: number; finals: number; edits: number };

const str = (v: unknown): v is string => typeof v === "string";
const num = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

/** Parse one server message; anything malformed or unknown → null (ignored by the UI). */
export function parseVoiceMessage(raw: unknown): VoiceServerMessage | null {
  if (!str(raw)) return null;
  let m: unknown;
  try {
    m = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!m || typeof m !== "object") return null;
  const o = m as Record<string, unknown>;
  const turn = str(o.turn_id) ? o.turn_id : null;
  switch (o.type) {
    case "ready":
      if (!str(o.mode) || !num(o.sample_rate) || !num(o.max_seconds)) return null;
      return {
        type: "ready",
        mode: o.mode,
        model: str(o.model) ? o.model : "",
        keywords: Array.isArray(o.keywords) ? o.keywords.filter(str) : [],
        sample_rate: o.sample_rate,
        max_seconds: o.max_seconds,
        max_bytes: num(o.max_bytes) ? o.max_bytes : 0,
        mock_script: str(o.mock_script) ? o.mock_script : undefined,
        note: str(o.note) ? o.note : undefined,
      };
    case "speech_start":
    case "speech_end":
      return { type: o.type, turn_id: turn, mode: str(o.mode) ? o.mode : "live" };
    case "partial":
    case "final":
      return str(o.text) ? { type: o.type, text: o.text, turn_id: turn, mode: str(o.mode) ? o.mode : "live" } : null;
    case "edit": {
      const r = o.result as Record<string, unknown> | undefined;
      if (!r || !str(r.transcript) || !Array.isArray(r.edits)) return null;
      return { type: "edit", turn_id: turn, result: r as unknown as LiveEditResult };
    }
    case "edit_error":
    case "warning":
    case "error":
      if (!str(o.message)) return null;
      return o.type === "edit_error"
        ? { type: "edit_error", turn_id: turn, code: str(o.code) ? o.code : "error", message: o.message }
        : { type: o.type, code: str(o.code) ? o.code : "error", message: o.message };
    case "capped":
      return (o.reason === "time" || o.reason === "size") && num(o.limit) ? { type: "capped", reason: o.reason, limit: o.limit } : null;
    case "pong":
      return { type: "pong" };
    case "closed":
      return {
        type: "closed",
        reason: str(o.reason) ? o.reason : "closed",
        seconds: num(o.seconds) ? o.seconds : 0,
        bytes: num(o.bytes) ? o.bytes : 0,
        finals: num(o.finals) ? o.finals : 0,
        edits: num(o.edits) ? o.edits : 0,
      };
    default:
      return null;
  }
}

/** Plain words for why a session ended (shown under the button). */
export function closedReasonText(reason: string, maxSeconds: number): string {
  switch (reason) {
    case "stopped":
      return "Stopped.";
    case "time_cap":
      return `Stopped at the ${Math.round(maxSeconds)} s limit for one live session.`;
    case "size_cap":
      return "Stopped: the session reached its audio size limit.";
    case "provider_ended":
      return "The transcription service ended the session.";
    case "client_gone":
      return "Disconnected.";
    case "error":
      return "Stopped after an error.";
    default:
      return "Session ended.";
  }
}
