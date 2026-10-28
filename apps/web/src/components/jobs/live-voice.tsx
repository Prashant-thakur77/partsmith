"use client";

import { AudioLines, Hand, Mic, Square } from "lucide-react";
import * as React from "react";
import type { EditResult } from "@/lib/api-types";
import { EditResultSchema } from "@/lib/api-types";
import {
  Downsampler,
  FrameChunker,
  closedReasonText,
  floatToPcm16,
  parseVoiceMessage,
  pcm16Bytes,
  rmsLevel,
  voiceSocketUrl,
  type VoiceServerMessage,
} from "@/lib/live-voice";
import { cn } from "@/lib/utils";
import { Button } from "../ui/button";
import { ModeBadge } from "../ui/provenance";

type Phase = "idle" | "connecting" | "listening" | "finishing";
type TalkMode = "hold" | "handsfree";

// Copies mic samples off the audio thread in ~2048-sample batches (about 43 ms at 48 kHz).
const WORKLET = `class PartsmithPcmTap extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Float32Array(2048); this.n = 0; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) for (let i = 0; i < ch.length; i++) { this.buf[this.n++] = ch[i]; if (this.n === this.buf.length) { this.port.postMessage(this.buf); this.buf = new Float32Array(2048); this.n = 0; } }
    return true;
  }
}
registerProcessor("partsmith-pcm-tap", PartsmithPcmTap);`;

const MAX_PENDING_FRAMES = 50; // 5 s of audio buffered while the socket opens
const WS_OVERRIDE = process.env.NEXT_PUBLIC_VOICE_WS_ORIGIN ?? "";

function liveVoiceSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof WebSocket !== "undefined" &&
    typeof AudioContext !== "undefined" &&
    typeof AudioWorkletNode !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia
  );
}

const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/**
 * Realtime voice edits: hold-to-talk or hands-free. Mic audio is resampled to 16 kHz PCM in the browser and streamed
 * to the API's live voice socket; partial transcripts show as you speak, and each finished sentence runs the same
 * voice→knob mapping and guards as a recorded clip (the knobs move, the diff shows below). The voice key stays on the
 * server; without one the session is a labelled mock. When live audio is unavailable the clip recorder remains.
 */
export function LiveVoice({ jobId, disabled, onEdit }: { jobId: string; disabled?: boolean; onEdit: (r: EditResult) => void }) {
  const [supported, setSupported] = React.useState<boolean | null>(null);
  React.useEffect(() => setSupported(liveVoiceSupported()), []);
  const [talk, setTalk] = React.useState<TalkMode>("hold");
  const [phase, setPhase] = React.useState<Phase>("idle");
  const [session, setSession] = React.useState<{ mode: string; maxSeconds: number; mockScript?: string; note?: string } | null>(null);
  const [partial, setPartial] = React.useState("");
  const [heard, setHeard] = React.useState<string[]>([]);
  const [notice, setNotice] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [elapsed, setElapsed] = React.useState(0);
  const [level, setLevel] = React.useState(0);
  const helpId = React.useId();

  const ws = React.useRef<WebSocket | null>(null);
  const audio = React.useRef<{ ctx: AudioContext; stream: MediaStream; node: AudioWorkletNode; url: string } | null>(null);
  const chunker = React.useRef(new FrameChunker());
  const pending = React.useRef<ArrayBuffer[]>([]);
  const ready = React.useRef(false);
  const startedAt = React.useRef(0);
  const wantStop = React.useRef(false);
  const starting = React.useRef(false); // guards double starts before the phase state re-renders
  const onEditRef = React.useRef(onEdit);
  onEditRef.current = onEdit;

  const stopAudio = React.useCallback(() => {
    const a = audio.current;
    audio.current = null;
    if (!a) return;
    a.node.port.onmessage = null;
    a.node.disconnect();
    a.stream.getTracks().forEach((t) => t.stop());
    void a.ctx.close().catch(() => undefined);
    URL.revokeObjectURL(a.url);
    setLevel(0);
  }, []);

  const sendFrame = React.useCallback((buf: ArrayBuffer) => {
    const sock = ws.current;
    if (sock && ready.current && sock.readyState === WebSocket.OPEN) sock.send(buf);
    else if (pending.current.length < MAX_PENDING_FRAMES) pending.current.push(buf);
  }, []);

  const finish = React.useCallback(() => {
    // stop capturing, send what is left, ask the server to wrap up (it answers with the last transcripts + `closed`)
    wantStop.current = true;
    stopAudio();
    const rest = chunker.current.flush();
    if (rest) sendFrame(pcm16Bytes(rest));
    const sock = ws.current;
    if (sock && ready.current && sock.readyState === WebSocket.OPEN) {
      sock.send(JSON.stringify({ type: "stop" }));
      setPhase("finishing");
    } else if (sock && sock.readyState === WebSocket.CONNECTING) {
      setPhase("finishing"); // `ready` will flush and stop
    } else {
      sock?.close();
      setPhase("idle");
    }
  }, [sendFrame, stopAudio]);

  // hold-to-talk release: may come before the socket exists (start() checks the flag when it gets there)
  const release = React.useCallback(() => {
    wantStop.current = true;
    if (ws.current) finish();
  }, [finish]);

  const handle = React.useCallback(
    (m: VoiceServerMessage) => {
      switch (m.type) {
        case "ready": {
          ready.current = true;
          startedAt.current = performance.now();
          setSession({ mode: m.mode, maxSeconds: m.max_seconds, mockScript: m.mock_script, note: m.note });
          const sock = ws.current;
          for (const buf of pending.current.splice(0)) sock?.send(buf);
          if (wantStop.current) {
            sock?.send(JSON.stringify({ type: "stop" }));
            setPhase("finishing");
          } else setPhase("listening");
          break;
        }
        case "partial":
          setPartial(m.text);
          break;
        case "final":
          setPartial("");
          setHeard((h) => [...h.slice(-2), m.text]);
          break;
        case "edit": {
          const r = EditResultSchema.safeParse(m.result);
          if (r.success) onEditRef.current(r.data);
          else setError("The server sent an edit this page could not read.");
          break;
        }
        case "edit_error":
          setError(`Edit not applied: ${m.message}`);
          break;
        case "capped":
          setNotice(m.reason === "time" ? `Reached the ${Math.round(m.limit)} s limit for one session.` : "Reached the audio size limit for one session.");
          stopAudio();
          setPhase("finishing");
          break;
        case "warning":
          setNotice(m.message);
          break;
        case "error":
          setError(m.message);
          break;
        case "closed":
          setNotice((n) => n ?? closedReasonText(m.reason, session?.maxSeconds ?? 60));
          break;
        default:
          break;
      }
    },
    [session?.maxSeconds, stopAudio],
  );
  const handleRef = React.useRef(handle);
  handleRef.current = handle;

  const start = React.useCallback(async () => {
    if (phase !== "idle" || disabled || starting.current || ws.current) return;
    starting.current = true;
    setError(null);
    setNotice(null);
    setPartial("");
    setSession(null);
    setElapsed(0);
    wantStop.current = false;
    ready.current = false;
    pending.current = [];
    chunker.current = new FrameChunker();
    setPhase("connecting");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    } catch {
      starting.current = false;
      setPhase("idle");
      setError("Microphone not available or permission denied. Use “Speak an edit” to record a clip instead.");
      return;
    }
    let url = "";
    try {
      const ctx = new AudioContext();
      const down = new Downsampler(ctx.sampleRate);
      url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
      await ctx.audioWorklet.addModule(url);
      const node = new AudioWorkletNode(ctx, "partsmith-pcm-tap", { numberOfInputs: 1, numberOfOutputs: 1, channelCount: 1 });
      ctx.createMediaStreamSource(stream).connect(node);
      node.connect(ctx.destination); // pulls the graph; the tap writes no output, so nothing is played back
      node.port.onmessage = (e: MessageEvent<Float32Array>) => {
        setLevel(rmsLevel(e.data));
        for (const f of chunker.current.push(floatToPcm16(down.push(e.data)))) sendFrame(pcm16Bytes(f));
      };
      audio.current = { ctx, stream, node, url };
    } catch {
      stream.getTracks().forEach((t) => t.stop());
      if (url) URL.revokeObjectURL(url);
      starting.current = false;
      setPhase("idle");
      setError("This browser cannot stream live audio. Use “Speak an edit” to record a clip instead.");
      return;
    }
    const sock = new WebSocket(voiceSocketUrl(jobId, window.location, WS_OVERRIDE));
    sock.binaryType = "arraybuffer";
    ws.current = sock;
    starting.current = false;
    sock.onmessage = (e) => {
      const m = parseVoiceMessage(e.data);
      if (m) handleRef.current(m);
    };
    sock.onerror = () => undefined; // onclose reports it
    sock.onclose = () => {
      if (ws.current !== sock) return;
      ws.current = null;
      stopAudio();
      if (!ready.current) setError((e) => e ?? "Live voice could not connect. Use “Speak an edit” to record a clip instead.");
      ready.current = false;
      setPartial("");
      setPhase("idle");
    };
    if (wantStop.current) finish(); // released before the mic opened
  }, [disabled, finish, jobId, phase, sendFrame, stopAudio]);

  // elapsed clock while listening
  React.useEffect(() => {
    if (phase !== "listening") return;
    const t = window.setInterval(() => setElapsed((performance.now() - startedAt.current) / 1000), 250);
    return () => window.clearInterval(t);
  }, [phase]);

  // leave nothing running when the page goes away
  React.useEffect(
    () => () => {
      const sock = ws.current;
      ws.current = null;
      sock?.close();
      stopAudio();
    },
    [stopAudio],
  );

  if (supported === null) return null;
  if (!supported) {
    return <p className="text-[12px] text-subtle">Live voice needs microphone streaming, which this browser does not offer. “Speak an edit” records a clip instead.</p>;
  }

  const active = phase === "connecting" || phase === "listening";
  const holdKeys = (e: React.KeyboardEvent) => e.key === " " || e.key === "Enter";
  const buttonLabel =
    phase === "finishing" ? "Finishing…" : active ? (talk === "hold" ? "Release to send" : "Stop listening") : talk === "hold" ? "Hold to talk" : "Start hands-free";

  return (
    <div className="space-y-2 rounded-md border border-border p-3" data-testid="live-voice">
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Live voice mode" className="inline-flex rounded-md border border-border p-0.5">
          {(["hold", "handsfree"] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={talk === m}
              disabled={phase !== "idle"}
              onClick={() => setTalk(m)}
              className={cn(
                "inline-flex items-center gap-1 rounded px-2 py-1 text-[12px] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent disabled:opacity-60",
                talk === m ? "bg-surface-3 font-medium text-fg" : "text-muted hover:text-fg",
              )}
            >
              {m === "hold" ? <Hand className="size-3.5" aria-hidden /> : <AudioLines className="size-3.5" aria-hidden />}
              {m === "hold" ? "Hold to talk" : "Hands-free"}
            </button>
          ))}
        </div>
        <Button
          type="button"
          size="sm"
          variant={active ? "danger" : "outline"}
          disabled={disabled || phase === "finishing"}
          aria-pressed={active}
          aria-describedby={helpId}
          onPointerDown={(e) => {
            if (talk !== "hold" || e.button !== 0) return;
            e.currentTarget.setPointerCapture(e.pointerId);
            void start();
          }}
          onPointerUp={() => talk === "hold" && release()}
          onPointerCancel={() => talk === "hold" && release()}
          onKeyDown={(e) => {
            if (talk !== "hold" || !holdKeys(e)) return;
            e.preventDefault();
            if (!e.repeat) void start();
          }}
          onKeyUp={(e) => {
            if (talk !== "hold" || !holdKeys(e)) return;
            e.preventDefault();
            release();
          }}
          onClick={(e) => {
            // hands-free toggles; in hold mode only assistive-technology clicks (no pointer, no key) toggle
            if (talk === "hold" && e.detail !== 0) return;
            if (active) finish();
            else void start();
          }}
        >
          {active ? <Square aria-hidden /> : <Mic aria-hidden />}
          {buttonLabel}
        </Button>
        {session ? <ModeBadge mode={session.mode} /> : null}
        {phase === "listening" ? (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-bad" role="status">
            <span className="size-2 animate-pulse rounded-full bg-bad" aria-hidden />
            Listening <span className="font-mono tnum">{clock(elapsed)} / {clock(session?.maxSeconds ?? 60)}</span>
          </span>
        ) : phase === "connecting" ? (
          <span className="text-[12px] text-muted" role="status">
            Connecting…
          </span>
        ) : null}
        {phase === "listening" ? (
          <span className="h-1.5 w-16 overflow-hidden rounded-full bg-surface-3" aria-hidden>
            <span className="block h-full bg-bad transition-[width] duration-75" style={{ width: `${Math.round(Math.min(1, level * 4) * 100)}%` }} />
          </span>
        ) : null}
      </div>
      <p id={helpId} className="text-[11px] text-subtle">
        {talk === "hold"
          ? "Hold the button (or Space) while you speak; release to apply. English, Hindi or a mix."
          : "Talk naturally; each finished sentence is applied. Up to 1 minute per session."}
        {session?.mode === "mock" && session.mockScript ? <> Mock: replays “{session.mockScript}” as you talk.</> : null}
      </p>
      <div aria-live="polite" aria-atomic="true" className="min-h-5 text-[13px]">
        {partial ? <span className="text-muted italic">{partial}…</span> : heard.length ? <span>Heard: <q className="text-fg">{heard[heard.length - 1]}</q></span> : null}
      </div>
      {notice ? <p className="text-[12px] text-muted" role="status">{notice}</p> : null}
      {error ? (
        <p className="text-[12px] text-bad" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
