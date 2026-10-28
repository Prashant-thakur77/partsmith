"use client";

/**
 * Fail → fix history: one tile per build round (error, per-view Hausdorff against the limit, knobs changed, the
 * verifier's verdict), failing rounds in amber/red and a verified one in green, each with an icon and words so colour
 * is never the only cue. Selecting a round shows its residual overlays. Everything comes from the job's events
 * (`roundsFromEvents`); a single round says so plainly.
 */
import { CircleCheck, CircleDashed, CircleX, ImageOff, TriangleAlert } from "lucide-react";
import * as React from "react";
import { artifactUrl } from "@/lib/api";
import type { JobEvent } from "@/lib/api-types";
import { editsText, roundsFromEvents, type FixRound, type RoundVerdict } from "@/lib/fix-rounds";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";

const VERDICT: Record<RoundVerdict, { word: string; icon: typeof CircleCheck; tile: string; text: string }> = {
  verified: { word: "verified", icon: CircleCheck, tile: "border-ok-border bg-ok-soft", text: "text-ok" },
  best_effort: { word: "not verified", icon: TriangleAlert, tile: "border-warn-border bg-warn-soft", text: "text-warn" },
  failed: { word: "failed", icon: CircleX, tile: "border-bad-border bg-bad-soft", text: "text-bad" },
  unknown: { word: "no verdict yet", icon: CircleDashed, tile: "border-border bg-surface-2", text: "text-muted" },
};

function roundName(r: FixRound): string {
  return r.firstBuild && r.iter === 1 ? "First build" : `Round ${r.iter}`;
}

/** ✓ / ✗ for a view's Hausdorff against the limit, with words for screen readers. */
function LimitMark({ within }: { within: boolean | null }) {
  if (within == null) return null;
  return (
    <>
      <span aria-hidden>{within ? " ✓" : " ✗"}</span>
      <span className="sr-only">{within ? " (within the limit)" : " (over the limit)"}</span>
    </>
  );
}

export function FixHistoryStrip({ events, className }: { events: JobEvent[]; className?: string }) {
  const s = React.useMemo(() => roundsFromEvents(events), [events]);
  const [sel, setSel] = React.useState<number | null>(null);
  const titleId = React.useId();
  const panelId = React.useId();
  if (!s.rounds.length) return null;
  const selected = s.rounds.find((r) => r.iter === sel) ?? null;
  const lastIter = s.rounds.at(-1)!.iter;
  return (
    <section aria-labelledby={titleId} className={cn("min-w-0 max-w-full rounded-lg border border-border bg-surface p-3", className)}>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 id={titleId} className="text-[11px] font-medium tracking-[0.08em] text-subtle uppercase">
          Fail → fix history
        </h2>
        <p className="text-[12.5px] font-medium text-fg">
          {s.headline}
          {s.limitMm != null ? <span className="ml-2 font-mono text-[11px] font-normal text-subtle tnum">limit {fmtNum(s.limitMm)} mm</span> : null}
        </p>
      </div>
      <ol className="scrollbar-thin relative flex gap-2 overflow-x-auto pb-1" aria-label="Build rounds, oldest first">
        {s.rounds.map((r, i) => {
          const v = VERDICT[r.verdict];
          const Icon = v.icon;
          const on = r.iter === sel;
          return (
            <li key={r.iter} className="flex shrink-0 items-stretch gap-2">
              {i > 0 ? (
                <span aria-hidden className="self-center text-subtle">
                  →
                </span>
              ) : null}
              <button
                type="button"
                aria-pressed={on}
                aria-controls={panelId}
                onClick={() => setSel(on ? null : r.iter)}
                className={cn(
                  "flex w-[188px] flex-col gap-1 rounded-md border px-2.5 py-2 text-left text-[12px] hover:brightness-[0.98]",
                  v.tile,
                  on && "ring-2 ring-[var(--ring)] ring-offset-1 ring-offset-[var(--surface)]",
                )}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="font-medium text-fg">{roundName(r)}</span>
                  <span className={cn("inline-flex items-center gap-1 text-[11px] font-medium", v.text)}>
                    <Icon className="size-3.5" aria-hidden />
                    {v.word}
                    {r.iter === lastIter && s.final ? <span className="text-subtle">· final</span> : null}
                  </span>
                </span>
                <span className="font-mono text-[13px] text-fg tnum">
                  {r.maxErrorMm != null ? `${fmtNum(r.maxErrorMm)} mm` : "—"}
                  <span className="ml-1 font-sans text-[10.5px] text-subtle">max error</span>
                </span>
                {r.views.length ? (
                  <span className="flex flex-wrap gap-x-2 gap-y-0.5 font-mono text-[11px] tnum">
                    {r.views.map((w) => (
                      <span key={w.view} className={w.withinLimit == null ? "text-muted" : w.withinLimit ? "text-ok" : "text-bad"}>
                        {w.view} {w.hausdorffMm != null ? fmtNum(w.hausdorffMm) : "—"}
                        <LimitMark within={w.withinLimit} />
                      </span>
                    ))}
                  </span>
                ) : null}
                <span className="line-clamp-2 text-[11px] text-muted" title={editsText(r)}>
                  <span className="sr-only">Changed: </span>
                  {editsText(r)}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      <div id={panelId} role="region" aria-live="polite" aria-label="Selected round">
        {selected ? <RoundDetail r={selected} limit={s.limitMm} /> : (
          <p className="mt-1 text-[11.5px] text-subtle">
            Select a round to see its overlay. Per view: Hausdorff distance against the limit (✓ within, ✗ over); the verdict also needs the IoU and the part tests.
          </p>
        )}
      </div>
    </section>
  );
}

function RoundDetail({ r, limit }: { r: FixRound; limit: number | null }) {
  return (
    <div className="mt-2 space-y-2 border-t border-border pt-2 text-[12px]">
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted">
        <span>
          <span className="text-subtle">Verifier: </span>
          <span className="text-fg">{r.verdictText || "no verify result recorded"}</span>
        </span>
        {r.testsTotal ? (
          <span className="font-mono tnum">
            tests {r.testsPassed}/{r.testsTotal}
          </span>
        ) : null}
        {r.iou != null ? <span className="font-mono tnum">min IoU {fmtNum(r.iou, 3)}</span> : null}
        <span>
          <span className="text-subtle">Changed: </span>
          {editsText(r)}
        </span>
      </div>
      {r.views.length ? (
        <ul className="flex flex-wrap gap-x-4 gap-y-0.5 font-mono text-[11.5px] tnum" aria-label="Per view">
          {r.views.map((v) => (
            <li key={v.view}>
              {v.view}: Hausdorff {v.hausdorffMm != null ? `${fmtNum(v.hausdorffMm)} mm` : "—"}
              {v.withinLimit != null && limit != null ? (v.withinLimit ? ` ≤ ${fmtNum(limit)} mm` : ` > ${fmtNum(limit)} mm`) : ""}
              <LimitMark within={v.withinLimit} />
              {v.iou != null ? ` · IoU ${fmtNum(v.iou, 3)}` : ""}
            </li>
          ))}
        </ul>
      ) : null}
      {r.overlays.length ? (
        <div className="flex gap-2 overflow-x-auto">
          {r.overlays.map((o) => (
            <figure key={o.url} className="w-[260px] shrink-0 space-y-1">
              <a href={artifactUrl(o.url)} target="_blank" rel="noreferrer noopener" className="block overflow-hidden rounded-md border border-border bg-[var(--viewer-bg)]">
                {/* eslint-disable-next-line @next/next/no-img-element -- API overlay image of unknown size */}
                <img src={artifactUrl(o.url)} alt={`${o.label}: model outline over the ${o.view} photo, differences highlighted`} loading="lazy" decoding="async" className="aspect-[4/3] w-full object-contain" />
              </a>
              <figcaption className="text-[11px] text-subtle">{o.label}</figcaption>
            </figure>
          ))}
        </div>
      ) : (
        <p className="flex items-center gap-1.5 text-muted">
          <ImageOff className="size-3.5" aria-hidden /> No overlay was stored for this round.
        </p>
      )}
    </div>
  );
}
