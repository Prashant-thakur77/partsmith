"use client";

import { useMutation } from "@tanstack/react-query";
import { Mic, Square } from "lucide-react";
import * as React from "react";
import { api } from "@/lib/api";
import type { TranscribeResult } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { Button } from "./ui/button";
import { ErrorState } from "./ui/error-state";
import { ModeBadge } from "./ui/provenance";
import { Spinner } from "./ui/spinner";

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
  // Decided after mount so server and client render the same markup.
  const [supported, setSupported] = React.useState(false);
  React.useEffect(() => setSupported("MediaRecorder" in window && !!navigator.mediaDevices?.getUserMedia), []);

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

/**
 * Record speech and transcribe it on the server (`POST /transcribe`, Muse Voice Transcribe or a labelled mock).
 * Hands the text back; shows the mode and any note (mock transcripts say so).
 */
export function TranscribeButton({
  onText,
  languageHint,
  label = "Speak",
  className,
  disabled,
}: {
  onText: (text: string, result: TranscribeResult) => void;
  languageHint?: string;
  label?: string;
  className?: string;
  disabled?: boolean;
}) {
  const t = useMutation({ mutationFn: (audio: Blob) => api.transcribe(audio, languageHint), onSuccess: (r) => r.text.trim() && onText(r.text.trim(), r) });
  return (
    <div className={cn("flex flex-col items-end gap-1", className)}>
      <div className="flex items-center gap-2">
        {t.isPending ? (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-muted" role="status">
            <Spinner className="size-3.5" label="Transcribing" /> transcribing…
          </span>
        ) : t.data ? (
          <span className="inline-flex items-center gap-1.5 text-[11px] text-subtle">
            <ModeBadge mode={t.data.mode} hideLive />
            {t.data.note ? <span className="max-w-56 truncate" title={t.data.note}>{t.data.note}</span> : null}
          </span>
        ) : null}
        <VoiceRecordButton onAudio={(a) => t.mutate(a)} label={label} disabled={disabled || t.isPending} />
      </div>
      {t.isError ? <ErrorState error={t.error} compact what="the transcription" className="py-2" /> : null}
    </div>
  );
}
