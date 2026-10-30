"use client";

import { CheckCircle2, ShieldAlert, XCircle } from "lucide-react";
import * as React from "react";
import { ResidualTable } from "@/components/jobs/residual-table";
import { Eyebrow } from "@/components/ui/card";
import type { Verification } from "@/lib/api-types";
import { cn } from "@/lib/utils";

const VIEW_NAME: Record<string, string> = { top: "From above", side: "From the side", mating: "Where it fits" };
const SHOWN_ROWS = 5;

/**
 * The code's verdict in plain words: does the model match the photo, by how much on each view, against which limit,
 * and which sizes are off. Every number is the verifier's (`verification.json`); nothing is computed here.
 */
export function MeasureCheck({ verification, className }: { verification: Verification | null | undefined; className?: string }) {
  const [all, setAll] = React.useState(false);
  if (!verification) {
    return (
      <section aria-label="Measurements" className={cn("rounded-lg border border-border bg-surface p-4", className)}>
        <Eyebrow>Measurements · code decides</Eyebrow>
        <p className="mt-2 text-[13px] text-muted">No measurement check for this round yet.</p>
      </section>
    );
  }
  const limit = verification.thresholds.hausdorff_mm;
  const pass = verification.status === "verified";
  const blocking = verification.vetoes.filter((v) => v.severity === "blocking");
  const sorted = [...verification.residuals].sort((a, b) => Math.abs(b.delta_mm) - Math.abs(a.delta_mm));
  const shown = all ? sorted : sorted.slice(0, SHOWN_ROWS);
  const worst = verification.max_error_mm;
  // the verifier's own failing checks, in words: views over the limit, then failed must-pass part tests
  const why = [
    ...verification.views
      .filter((v) => v.hausdorff_mm > limit)
      .map((v) => `${VIEW_NAME[v.view] ?? v.view}: outline off by ${v.hausdorff_mm.toFixed(2)} mm${v.view === "top" ? " (circled on the photo)" : ""}`),
    ...verification.tests
      .filter((t) => !t.passed && t.priority === "P0")
      .slice(0, 3)
      .map((t) => (t.value != null && t.expected != null ? `${t.description}: model ${t.value.toFixed(2)}, photo ${t.expected.toFixed(2)}` : t.description)),
  ];
  return (
    <section aria-label="Measurements" className={cn("space-y-3 rounded-lg border border-border bg-surface p-4", className)}>
      <Eyebrow>Measurements · code decides</Eyebrow>
      <div className={cn("flex items-start gap-2 rounded-md border px-3 py-2", pass ? "border-ok-border bg-ok-soft" : "border-warn-border bg-warn-soft")}>
        {pass ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden /> : <XCircle className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />}
        <p className="text-[13px] leading-snug">
          <span className="font-semibold">{pass ? "Matches the photo." : verification.status === "failed" ? "Not a usable solid." : "Does not match the photo yet."}</span>{" "}
          {worst != null ? (
            <>
              Worst gap <span className="font-mono tnum">{worst.toFixed(2)} mm</span>, limit <span className="font-mono tnum">{limit.toFixed(2)} mm</span>.
            </>
          ) : null}
        </p>
      </div>
      {!pass && why.length ? (
        <ul className="space-y-0.5 text-[12.5px]" aria-label="Why it does not pass">
          {why.map((w) => (
            <li key={w} className="flex gap-1.5">
              <span aria-hidden className="text-warn">
                •
              </span>
              {w}
            </li>
          ))}
        </ul>
      ) : null}
      {verification.views.length ? (
        <ul className="space-y-1.5" aria-label="Gap per view">
          {verification.views.map((v) => {
            const ok = v.hausdorff_mm <= limit;
            const fill = Math.min(1, v.hausdorff_mm / (limit * 2));
            return (
              <li key={v.view} className="grid grid-cols-[7.5rem_minmax(0,1fr)_4.5rem] items-center gap-2 text-[12px]">
                <span className="text-muted">{VIEW_NAME[v.view] ?? v.view}</span>
                <span className="relative h-2 overflow-hidden rounded-full bg-surface-2" aria-hidden>
                  <span className={cn("absolute inset-y-0 left-0 rounded-full", ok ? "bg-ok" : "bg-warn")} style={{ width: `${fill * 100}%` }} />
                  <span className="absolute inset-y-0 left-1/2 w-px bg-fg/40" title={`limit ${limit} mm`} />
                </span>
                <span className={cn("text-right font-mono tnum", ok ? "text-ok" : "text-warn")}>{v.hausdorff_mm.toFixed(2)} mm</span>
              </li>
            );
          })}
        </ul>
      ) : null}
      {blocking.length ? (
        <div className="flex items-start gap-2 rounded-md border border-bad-border bg-bad-soft px-3 py-2 text-[12.5px]">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-bad" aria-hidden />
          <p>
            <span className="font-medium">Blocked by the judge:</span> {blocking.map((v) => `${v.feature}: ${v.issue}`).join("; ")}
          </p>
        </div>
      ) : null}
      {sorted.length ? (
        <div className="space-y-1">
          <p className="text-[12px] text-muted">Sizes from the photo vs the model, biggest difference first</p>
          <ResidualTable residuals={shown} />
          {sorted.length > SHOWN_ROWS ? (
            <button type="button" onClick={() => setAll((x) => !x)} className="text-[12px] text-accent-text hover:underline">
              {all ? "Show fewer" : `Show all ${sorted.length} sizes`}
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
