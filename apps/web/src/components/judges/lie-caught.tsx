"use client";

import { Ban, Bot, ShieldCheck, TriangleAlert } from "lucide-react";
import * as React from "react";
import { apiUrl } from "@/lib/api";
import type { BypassReport, CaughtLie } from "@/lib/api-types";
import { exportLine } from "@/lib/bypass";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { Eyebrow } from "../ui/card";

/** URL of a report file written by `eval/` (path relative to eval/reports, as stored in the JSON). */
export function reportFileUrl(rel: string): string {
  return apiUrl(`/bench/files/${rel.split("/").map(encodeURIComponent).join("/")}`);
}

const TITLES: Record<string, string> = {
  says_verified: "It says “verified”",
  fake_break: "It blames a break that isn’t there",
};

function LieCard({ c }: { c: CaughtLie }) {
  const err = c.verifier.max_error_mm;
  const lim = c.verifier.threshold_mm;
  const line = exportLine(c);
  const titleId = React.useId();
  return (
    <article aria-labelledby={titleId} className="flex flex-col overflow-hidden rounded-xl border border-border bg-surface">
      <header className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <h3 id={titleId} className="text-[14px] font-semibold">
          {TITLES[c.id] ?? c.id.replace(/_/g, " ")}
        </h3>
        <Badge tone="mock" className="ml-auto whitespace-normal">
          scripted mock attack (no model call)
        </Badge>
      </header>

      <div className="space-y-4 p-4">
        <figure className="space-y-1.5">
          <Eyebrow className="flex items-center gap-1.5">
            <Bot className="size-3.5" aria-hidden /> The model claims
          </Eyebrow>
          <blockquote className="rounded-lg border border-border bg-surface-2 px-3 py-2.5 text-[14px] leading-6 text-fg">“{c.claim}”</blockquote>
          <figcaption className="text-[12px] text-muted">{c.attack}</figcaption>
        </figure>

        <figure className="space-y-1.5">
          <Eyebrow className="flex items-center gap-1.5">
            <ShieldCheck className="size-3.5" aria-hidden /> The verifier measures
          </Eyebrow>
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="font-mono text-[26px] leading-none font-semibold text-bad tnum">{err != null ? `${fmtNum(err)} mm` : "—"}</span>
            <span className="text-[13px] text-muted">
              max error · limit {fmtNum(lim)} mm · <span className="font-medium text-fg">{c.verifier.verified ? "verified" : c.verifier.status.replace("_", " ")}</span>
            </span>
          </div>
          {c.overlay ? (
            <>
              {/* eslint-disable-next-line @next/next/no-img-element -- report file served by the API */}
              <img
                src={reportFileUrl(c.overlay)}
                alt={`Verifier overlay, ${c.overlay_note || "top view"}. Grey: model and photo agree; orange: model material the photo lacks; blue: photo material the model lacks. Maximum error ${err != null ? fmtNum(err) : "unknown"} millimetres against a ${fmtNum(lim)} millimetre limit.`}
                loading="lazy"
                decoding="async"
                width={c.overlay_px?.[0] ?? 960}
                height={c.overlay_px?.[1] ?? 720}
                className="h-auto w-full rounded-md border border-border bg-white"
              />
              <figcaption className="text-[12px] text-muted">{c.overlay_note}</figcaption>
            </>
          ) : (
            <figcaption className="text-[12px] text-muted">No overlay image in this report.</figcaption>
          )}
          {c.verifier.failed_tests.length ? (
            <p className="text-[12px] text-muted">
              Failed checks: <span className="font-mono text-fg">{c.verifier.failed_tests.join(", ")}</span>
            </p>
          ) : null}
        </figure>

        <div
          className={cn(
            "flex items-start gap-2 rounded-lg border p-3 text-[13px]",
            c.export.ok ? "border-ok-border bg-ok-soft" : "border-bad-border bg-bad-soft",
          )}
        >
          {c.export.ok ? <ShieldCheck className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden /> : <Ban className="mt-0.5 size-4 shrink-0 text-bad" aria-hidden />}
          <div className="space-y-0.5">
            <p className="font-semibold text-fg">
              {line.title}: <span className="font-normal">{c.export.reason}</span>
            </p>
            {line.sub ? <p className="text-muted">{line.sub}</p> : null}
          </div>
        </div>
      </div>
    </article>
  );
}

/**
 * "A lying model, caught": the lying-brain suite's evidence (`eval/bypass.py` → bench evidence). Every number and
 * sentence below is read from the report JSON; nothing is typed here.
 */
export function LieCaught({ report }: { report: BypassReport | null | undefined }) {
  if (!report) {
    return (
      <p className="flex items-center gap-2 rounded-lg border border-dashed border-border-strong bg-surface px-4 py-3 text-[13px] text-muted">
        <TriangleAlert className="size-4 shrink-0" aria-hidden /> Not run yet: this evidence appears once the lying-model test has been run.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <p className="text-[13px] text-muted">
        <span className="font-semibold text-fg tnum">
          {report.blocked}/{report.attempts}
        </span>{" "}
        lying-model attacks blocked by code ({report.suite}).
      </p>
      {report.caught.length ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {report.caught.map((c) => (
            <LieCard key={c.id} c={c} />
          ))}
        </div>
      ) : (
        <p className="text-[13px] text-muted">
          This report has no caught-lie images yet.
        </p>
      )}
      {report.rows.length ? (
        <details className="group rounded-lg border border-border bg-surface">
          <summary className="cursor-pointer px-4 py-2.5 text-[13px] font-medium select-none">
            Every attack and the layer of code that stopped it ({report.rows.length})
          </summary>
          <div tabIndex={0} role="region" aria-label="Lying-model attacks" className="scrollbar-thin overflow-x-auto border-t border-border">
            <table className="w-full min-w-[560px] text-[12.5px]">
              <thead className="bg-surface-2 text-left text-[11px] text-subtle">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">Attack</th>
                  <th scope="col" className="px-3 py-2 font-medium">Stopped by</th>
                  <th scope="col" className="px-3 py-2 font-medium">Result</th>
                </tr>
              </thead>
              <tbody>
                {report.rows.map((r) => (
                  <tr key={r.id} className="border-t border-border align-top">
                    <th scope="row" className="px-3 py-2 text-left font-normal">
                      {r.attack}
                    </th>
                    <td className="px-3 py-2 font-mono text-[11.5px] whitespace-nowrap">{r.blocked_by}</td>
                    <td className="px-3 py-2">
                      <Badge tone={r.blocked ? "ok" : "bad"}>{r.blocked ? "blocked" : "NOT blocked"}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ) : null}
    </div>
  );
}
