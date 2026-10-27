"use client";

import { Mic, Square } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";
import { Button } from "./ui/button";

/** Records audio with MediaRecorder and hands the Blob to `onAudio` (the server transcribes it). */
export function VoiceRecordButton({
  onAudio,
  disabled,
  label = "Speak",
  className,
}: {
  onAudio: (blob: Blob) => void;
  disabled?: boolean;
  label?: string;
  className?: string;
}) {
  const [rec, setRec] = React.useState<MediaRecorder | null>(null);
  const [secs, setSecs] = React.useState(0);
  const [err, setErr] = React.useState<string | null>(null);
  const supported = typeof window !== "undefined" && "MediaRecorder" in window && !!navigator.mediaDevices?.getUserMedia;

  React.useEffect(() => {
    if (!rec) return;
    const t = window.setInterval(() => setSecs((s) => s + 1), 1000);
    return () => window.clearInterval(t);
  }, [rec]);

  const start = async () => {
    setErr(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      const chunks: BlobPart[] = [];
      mr.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      mr.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        onAudio(new Blob(chunks, { type: mr.mimeType || "audio/webm" }));
      };
      mr.start();
      setSecs(0);
      setRec(mr);
    } catch {
      setErr("Microphone not available or permission denied.");
    }
  };
  const stop = () => {
    rec?.stop();
    setRec(null);
  };

  if (!supported) return null;
  return (
    <div className={cn("inline-flex items-center gap-2", className)}>
      <Button
        variant={rec ? "danger" : "outline"}
        size="sm"
        onClick={rec ? stop : start}
        disabled={disabled}
        aria-pressed={!!rec}
        aria-label={rec ? "Stop recording" : label}
      >
        {rec ? <Square aria-hidden /> : <Mic aria-hidden />}
        {rec ? <span className="font-mono tnum">Stop · 0:{String(secs).padStart(2, "0")}</span> : label}
      </Button>
      {err ? <span className="text-[12px] text-bad">{err}</span> : null}
    </div>
  );
}

type SpeechRec = {
  lang: string;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
};

/** Browser dictation (Web Speech API) for short text fields. Hidden where the browser lacks it. */
export function DictateButton({ onText, lang = "en-IN", className }: { onText: (t: string) => void; lang?: string; className?: string }) {
  const [on, setOn] = React.useState(false);
  const ref = React.useRef<SpeechRec | null>(null);
  const [supported, setSupported] = React.useState(false);
  React.useEffect(() => {
    const w = window as unknown as { SpeechRecognition?: new () => SpeechRec; webkitSpeechRecognition?: new () => SpeechRec };
    setSupported(!!(w.SpeechRecognition ?? w.webkitSpeechRecognition));
  }, []);
  if (!supported) return null;
  const toggle = () => {
    if (on) {
      ref.current?.stop();
      return;
    }
    const w = window as unknown as { SpeechRecognition?: new () => SpeechRec; webkitSpeechRecognition?: new () => SpeechRec };
    const Ctor = (w.SpeechRecognition ?? w.webkitSpeechRecognition)!;
    const r = new Ctor();
    r.lang = lang;
    r.interimResults = false;
    r.onresult = (e) => {
      const t = Array.from(e.results)
        .map((res) => res[0]?.transcript ?? "")
        .join(" ");
      if (t.trim()) onText(t.trim());
    };
    r.onend = () => setOn(false);
    r.onerror = () => setOn(false);
    ref.current = r;
    r.start();
    setOn(true);
  };
  return (
    <Button variant={on ? "danger" : "outline"} size="sm" onClick={toggle} aria-pressed={on} className={className}>
      {on ? <Square aria-hidden /> : <Mic aria-hidden />}
      {on ? "Listening… tap to stop" : "Dictate"}
    </Button>
  );
}
