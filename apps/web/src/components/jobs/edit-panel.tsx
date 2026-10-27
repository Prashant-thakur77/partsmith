"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowRight, MessageSquareText, Send } from "lucide-react";
import * as React from "react";
import { api } from "@/lib/api";
import type { EditResult } from "@/lib/api-types";
import { fmtNum, fmtPct, paramLabel } from "@/lib/format";
import { VoiceRecordButton } from "../voice-button";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { ErrorState } from "../ui/error-state";
import { Input } from "../ui/input";
import { ModeBadge } from "../ui/provenance";
import { Spinner } from "../ui/spinner";

/** Voice or text edits ("hole 0.2 mm bigger"). The server maps words to knobs, clamps them to PARAMS and re-bakes. */
export function EditPanel({ jobId, onResult, disabled }: { jobId: string; onResult: (r: EditResult) => void; disabled?: boolean }) {
  const [text, setText] = React.useState("");
  const edit = useMutation({
    mutationFn: (input: { text: string } | { audio: Blob }) => ("text" in input ? api.editText(jobId, input.text) : api.editAudio(jobId, input.audio)),
    onSuccess: (r) => {
      onResult(r);
      setText("");
    },
  });
  const r = edit.data;
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-[13px] font-semibold">
          <MessageSquareText className="size-4 text-muted" aria-hidden /> Edit by talking
        </h2>
        <VoiceRecordButton onAudio={(audio) => edit.mutate({ audio })} disabled={disabled || edit.isPending} label="Speak an edit" />
      </div>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) edit.mutate({ text: text.trim() });
        }}
      >
        <Input
          aria-label="Describe an edit"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="e.g. make the hole 0.2 mm bigger for PLA"
          disabled={disabled}
        />
        <Button type="submit" variant="outline" disabled={disabled || !text.trim() || edit.isPending} aria-label="Apply edit">
          {edit.isPending ? <Spinner label="Applying" /> : <Send aria-hidden />}
        </Button>
      </form>
      {edit.isError ? <ErrorState error={edit.error} compact what="the edit" /> : null}
      {r ? (
        <div className="space-y-2 rounded-md border border-border bg-surface-2 p-3 text-[12px]" aria-live="polite">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-muted">Heard:</span> <q className="text-fg">{r.transcript}</q>
            <ModeBadge mode={r.mode} hideLive />
            <Badge tone="neutral" className="font-mono tnum">confidence {fmtPct(r.confidence, 0)}</Badge>
          </div>
          {r.edits.length ? (
            <ul className="space-y-1">
              {r.edits.map((e) => (
                <li key={e.param} className="flex flex-wrap items-center gap-1.5">
                  <Badge tone="ok">applied</Badge>
                  <span className="font-medium">{paramLabel(e.param)}</span>
                  <span className="font-mono tnum text-muted">{fmtNum(e.from)}</span>
                  <ArrowRight className="size-3 text-subtle" aria-hidden />
                  <span className="font-mono tnum text-fg">{fmtNum(e.to)}</span>
                  {e.reason ? <span className="text-subtle">· {e.reason}</span> : null}
                </li>
              ))}
            </ul>
          ) : null}
          {r.not_understood.map((n) => (
            <div key={n} className="flex items-center gap-1.5">
              <Badge tone="warn">not understood</Badge> <span className="text-muted">{n}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
