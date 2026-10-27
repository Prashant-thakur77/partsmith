"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { HelpCircle, Send } from "lucide-react";
import * as React from "react";
import { api } from "@/lib/api";
import type { QuestionEvent } from "@/lib/api-types";
import { DictateButton } from "../voice-button";
import { Button } from "../ui/button";
import { ErrorState } from "../ui/error-state";
import { Input } from "../ui/input";
import { Spinner } from "../ui/spinner";

/** The job paused to ask about a hidden dimension. Your answer is recorded as a user-stated value. */
export function QuestionPanel({ jobId, question }: { jobId: string; question: QuestionEvent }) {
  const qc = useQueryClient();
  const [value, setValue] = React.useState(question.default != null ? String(question.default) : "");
  const [via, setVia] = React.useState<"text" | "voice">("text");
  const id = React.useId();
  const answer = useMutation({
    mutationFn: (v: string | number) => api.answer(jobId, { id: question.id, value: v, via }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["job", jobId] }),
  });
  const num = question.expects === "number_mm";
  const bad = num && value.trim() !== "" && !Number.isFinite(Number(value.replace(",", ".")));
  const submit = (v?: string) => {
    const raw = (v ?? value).trim();
    if (!raw) return;
    answer.mutate(num ? Number(raw.replace(",", ".")) : raw);
  };
  return (
    <div role="region" aria-labelledby={`${id}-q`} className="space-y-3 rounded-lg border border-info/40 bg-info-soft p-4">
      <div className="flex items-start gap-2.5">
        <HelpCircle className="mt-0.5 size-4 shrink-0 text-info" aria-hidden />
        <div className="space-y-1">
          <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-info">Paused — needs your answer</div>
          <p id={`${id}-q`} className="text-[14px] leading-6 font-medium text-fg">
            {question.text}
          </p>
        </div>
      </div>
      {question.expects === "choice" && question.choices?.length ? (
        <div className="flex flex-wrap gap-2">
          {question.choices.map((c) => (
            <Button key={c} size="sm" variant="outline" onClick={() => submit(c)} disabled={answer.isPending}>
              {c}
            </Button>
          ))}
        </div>
      ) : (
        <form
          className="flex flex-wrap items-start gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <div className="relative min-w-0 flex-1">
            <Input
              autoFocus
              aria-label={num ? "Answer in millimetres" : "Answer"}
              inputMode={num ? "decimal" : "text"}
              value={value}
              onChange={(e) => {
                setValue(e.target.value);
                setVia("text");
              }}
              aria-invalid={bad || undefined}
              className={num ? "pr-10 font-mono tnum" : undefined}
              placeholder={num ? "e.g. 4.5" : "Type your answer"}
            />
            {num ? <span className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 font-mono text-[12px] text-subtle">mm</span> : null}
          </div>
          <DictateButton
            onText={(t) => {
              const m = t.match(/-?\d+(?:[.,]\d+)?/);
              setValue(num && m ? m[0].replace(",", ".") : t);
              setVia("voice");
            }}
          />
          <Button type="submit" variant="solid" size="md" disabled={bad || !value.trim() || answer.isPending}>
            {answer.isPending ? <Spinner className="text-inverse-fg" label="Sending" /> : <Send aria-hidden />} Answer
          </Button>
        </form>
      )}
      {bad ? <p className="text-[12px] text-bad">Enter a number in millimetres.</p> : null}
      {answer.isError ? <ErrorState error={answer.error} compact what="your answer" /> : null}
    </div>
  );
}
