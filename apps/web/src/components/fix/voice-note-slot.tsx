"use client";

import { FileAudio, Trash2 } from "lucide-react";
import * as React from "react";
import { audioTypeFromName, voiceNoteName, voiceNoteProblem } from "@/lib/evidence-notes";
import { useT } from "@/lib/i18n";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { VoiceRecordButton } from "../voice-button";

/**
 * Optional voice note about the walk-around clip: record in the browser (MediaRecorder) or pick an audio file. It is
 * sent with the clip as `narration`; the words steer the agent and never set a number. The same size/type rule as the
 * server is checked here so a refusal shows before the upload.
 */
export function VoiceNoteSlot({ value, onChange, hasClip }: { value: File | null; onChange: (f: File | null) => void; hasClip: boolean }) {
  const { t } = useT();
  const ref = React.useRef<HTMLInputElement>(null);
  const hintId = React.useId();
  const [url, setUrl] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (!value) return setUrl(null);
    const u = URL.createObjectURL(value);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [value]);
  const problem = value ? voiceNoteProblem(value.type, value.size) : null;
  const title = t("fix.voiceNote");

  return (
    <div className="rounded-lg border border-border bg-surface" role="group" aria-labelledby={`${hintId}-title`} aria-describedby={hintId}>
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-2">
          <h3 id={`${hintId}-title`} className="text-[13px] font-semibold">
            {title}
          </h3>
          <Badge tone="neutral">optional</Badge>
        </div>
        {value ? (
          <Button size="sm" variant="ghost" onClick={() => onChange(null)} aria-label={`Remove ${title.toLowerCase()}`}>
            <Trash2 aria-hidden /> Remove
          </Button>
        ) : null}
      </div>
      <input
        ref={ref}
        type="file"
        accept="audio/*,.m4a,.mp3,.wav,.ogg,.webm"
        className="sr-only"
        tabIndex={-1}
        aria-label={`Choose file: ${title.toLowerCase()}`}
        onChange={(e) => {
          const f = e.target.files?.[0] ?? null;
          const guessed = f && !f.type ? audioTypeFromName(f.name) : null;
          onChange(f && guessed ? new File([f], f.name, { type: guessed }) : f);
          e.target.value = "";
        }}
      />
      <div className="space-y-2.5 p-3">
        <p id={hintId} className="text-[12.5px] leading-5 text-muted">
          {t("fix.voiceNoteHint")}
        </p>
        {value ? (
          <div className="space-y-1.5">
            {url ? <audio src={url} controls preload="metadata" className="h-9 w-full max-w-md" aria-label={`${title} preview`} /> : null}
            <p className="font-mono text-[12px] text-muted tnum">
              {value.name} · {(value.size / 1e6).toFixed(2)} MB
            </p>
            {problem ? (
              <p role="alert" className="text-[12.5px] text-bad">
                {problem}
              </p>
            ) : null}
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <VoiceRecordButton
              label={t("fix.recordNote")}
              onAudio={(blob) => onChange(new File([blob], voiceNoteName(blob.type), { type: blob.type || "audio/webm" }))}
            />
            <Button size="sm" variant="outline" onClick={() => ref.current?.click()}>
              <FileAudio aria-hidden /> {t("fix.chooseAudio")}
            </Button>
          </div>
        )}
        {value && !hasClip ? <p className="text-[12.5px] text-warn">{t("fix.voiceNoteNeedsClip")}</p> : null}
      </div>
    </div>
  );
}
