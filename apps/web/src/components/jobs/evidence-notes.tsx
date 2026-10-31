"use client";

/**
 * Evidence shown next to the measurements and the verdict: the narrated walk-around (what the model heard and pointed
 * at, what code kept and dropped), the knobs no test checked (`Verification.unchecked`), the range a single photo allows
 * (`Measured.bound_mm`) and the badge on values measured from a narrated point. Wording only; code made every number.
 */
import { useQuery } from "@tanstack/react-query";
import { CircleSlash, Mic, Ruler } from "lucide-react";
import * as React from "react";
import { api } from "@/lib/api";
import type { UncheckedValue } from "@/lib/api-types";
import {
  BOUND_TIP,
  NARRATION_NOTE,
  boundText,
  measuredValuesText,
  narrationView,
  uncheckedReason,
} from "@/lib/evidence-notes";
import { fmtNum } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { ModeBadge, SourceBadge } from "../ui/provenance";
import { Tooltip } from "../ui/tooltip";

/** Same look as the other provenance badges: a value a model pointed at in the clip and code then measured. */
export function NarratedBadge() {
  return (
    <Tooltip content="Muse Spark pointed at this feature in the walk-around clip; code checked the point on its frame and measured it.">
      <Badge tone="info" tabIndex={0} className="cursor-help">
        <Mic aria-hidden />
        {NARRATION_NOTE}
      </Badge>
    </Tooltip>
  );
}

/** "photo allows lo–hi mm" under a measured value whose photo cannot pin it down. */
export function BoundNote({ bound, className }: { bound: readonly [number, number] | null | undefined; className?: string }) {
  const text = boundText(bound);
  if (!text) return null;
  return (
    <Tooltip content={BOUND_TIP}>
      <span tabIndex={0} className={cn("cursor-help font-mono text-[11px] text-warn underline decoration-dotted underline-offset-2 tnum", className)}>
        {text}
      </span>
    </Tooltip>
  );
}

/** Knobs no test compared with a photo: shown next to the verdict, labelled inferred and not verified. */
export function UncheckedList({
  items,
  className,
  as: H = "h2",
  collapsible = false,
}: {
  items: UncheckedValue[];
  className?: string;
  as?: "h2" | "h3" | "h4";
  /** Start closed behind a "Not checked against a photo (N)" disclosure (the job page: the verdict comes first). */
  collapsible?: boolean;
}) {
  const { t } = useT();
  const id = React.useId();
  if (!items.length) return null;
  const head = (
    <span className="flex flex-wrap items-center gap-2">
      <CircleSlash className="size-4 shrink-0 text-warn" aria-hidden />
      <H id={id} className="font-medium text-fg">
        {t("ver.unchecked")}
      </H>
      <span className="font-mono text-[11px] text-subtle tnum">({items.length})</span>
    </span>
  );
  const body = (
    <>
      <p className="text-[12px] text-muted">{t("ver.uncheckedHint")}</p>
      <UncheckedRows items={items} />
    </>
  );
  if (collapsible) {
    return (
      <details aria-labelledby={id} className={cn("group rounded-lg border border-border bg-surface-2 px-4 py-2.5 text-[12.5px]", className)}>
        <summary className="cursor-pointer list-none [&::-webkit-details-marker]:hidden">
          <span className="flex items-center gap-2">
            {head}
            <span aria-hidden className="ml-auto text-[11px] text-subtle group-open:hidden">show</span>
            <span aria-hidden className="ml-auto hidden text-[11px] text-subtle group-open:inline">hide</span>
          </span>
        </summary>
        <div className="mt-1.5 space-y-1.5">{body}</div>
      </details>
    );
  }
  return (
    <section role="note" aria-labelledby={id} className={cn("space-y-1.5 rounded-lg border border-border bg-surface-2 px-4 py-3 text-[12.5px]", className)}>
      {head}
      {body}
    </section>
  );
}

function UncheckedRows({ items }: { items: UncheckedValue[] }) {
  return (
      <ul className="space-y-1">
        {items.map((u) => {
          const why = u.note ? uncheckedReason(u.note) : "";
          return (
            <li key={u.param} className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <code className="font-mono text-[12px] text-fg">{u.param}</code>
              {u.label && u.label !== u.param ? <span className="text-muted">{u.label}</span> : null}
              <span className="font-mono text-fg tnum">
                {fmtNum(u.value)}
                {u.unit === "deg" ? "°" : u.unit ? <span className="ml-[0.25em] text-[0.9em] text-muted">{u.unit}</span> : null}
              </span>
              <SourceBadge source={u.source} />
              {why ? (
                u.note && u.note !== why ? (
                  <Tooltip content={u.note}>
                    <span tabIndex={0} className="cursor-help text-[11.5px] text-subtle underline decoration-dotted underline-offset-2">
                      {why}
                    </span>
                  </Tooltip>
                ) : (
                  <span className="text-[11.5px] text-subtle">{why}</span>
                )
              ) : null}
            </li>
          );
        })}
      </ul>
  );
}

/** The job's narration artifact: summary (steers only), points kept with their measurements, points dropped and why. */
export function NarrationPanel({ url }: { url: string }) {
  const { t } = useT();
  const titleId = React.useId();
  const q = useQuery({ queryKey: ["job-narration", url], queryFn: () => api.narration(url), staleTime: Infinity, retry: false });
  if (q.isPending) return null;
  if (q.isError || !q.data) {
    return <p className="text-[12px] text-muted">{t("narr.unreadable")}</p>;
  }
  const rec = q.data;
  const v = narrationView(rec);
  return (
    <section aria-labelledby={titleId} className="space-y-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={titleId} className="text-[11px] font-medium tracking-[0.08em] text-subtle uppercase">
          {t("narr.title")}
        </h2>
        <span className="flex items-center gap-1.5">
          <Tooltip content={t("narr.steersTip")}>
            <Badge tone="warn" tabIndex={0} className="cursor-help">
              {t("narr.steers")}
            </Badge>
          </Tooltip>
          <ModeBadge mode={rec.narration.mode} />
        </span>
      </div>
      {rec.narration.label && rec.narration.mode === "mock" ? <p className="text-[11.5px] text-subtle">{rec.narration.label}</p> : null}
      {v.summary.length ? (
        <dl className="space-y-1 text-[12.5px]">
          {v.summary.map((s) => (
            <div key={s.label} className="grid grid-cols-[minmax(0,7.5rem)_minmax(0,1fr)] gap-2">
              <dt className="text-muted">{s.label}</dt>
              <dd className="text-fg">{s.text}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {rec.narration.transcript ? (
        <details className="text-[12px] text-muted">
          <summary className="cursor-pointer rounded-sm select-none">{t("narr.transcript")}</summary>
          <p className="mt-1 italic">{rec.narration.transcript}</p>
        </details>
      ) : null}

      <div className="space-y-1">
        <h3 className="text-[12px] font-medium text-fg">
          {t("narr.kept")} <span className="font-mono text-subtle tnum">{v.kept.length}</span>
        </h3>
        {v.kept.length ? (
          <ul className="space-y-1.5 text-[12px]">
            {v.kept.map((p, i) => (
              <li key={`${p.name}-${i}`} className="space-y-0.5">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="font-mono text-fg">{p.name}</span>
                  <span className="text-subtle">{p.kind.replaceAll("_", " ")}</span>
                  {p.t_s != null ? <span className="font-mono text-[11px] text-subtle tnum">{t("narr.at", { t: fmtNum(p.t_s, 1) })}</span> : null}
                  <NarratedBadge />
                </div>
                {p.measured ? (
                  <p className="flex items-center gap-1 pl-0.5 font-mono text-[11.5px] text-muted tnum">
                    <Ruler className="size-3 shrink-0" aria-hidden />
                    {p.measured.ok ? measuredValuesText(p.measured.values_mm) || "measured" : `not measured: ${p.measured.reason}`}
                  </p>
                ) : null}
                {p.said ? <q className="block text-[11.5px] text-subtle italic">{p.said}</q> : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[12px] text-muted">{rec.points.length ? t("narr.noneKept") : t("narr.none")}</p>
        )}
        {v.otherMeasured.length ? (
          <ul className="space-y-0.5 text-[11.5px] text-muted">
            {v.otherMeasured.map((m) => (
              <li key={m.id} className="font-mono tnum">
                {m.id}: {m.ok ? measuredValuesText(m.values_mm) : `not measured: ${m.reason}`}
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      {v.dropped.length ? (
        <div className="space-y-1">
          <h3 className="text-[12px] font-medium text-fg">
            {t("narr.dropped")} <span className="font-mono text-subtle tnum">{v.dropped.length}</span>
          </h3>
          <ul className="space-y-1 text-[12px]">
            {v.dropped.map((p, i) => (
              <li key={`${p.name}-${i}`} className="flex flex-wrap items-baseline gap-x-1.5">
                <span className="font-mono text-fg line-through decoration-subtle">{p.name}</span>
                <span className="text-muted">— {p.reason || "no reason given"}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {!rec.same_placement ? <p className="text-[11.5px] text-warn">{t("narr.moved")}</p> : null}
      {rec.merged.length ? (
        <ul className="list-disc space-y-0.5 pl-4 text-[11.5px] text-subtle">
          {rec.merged.map((m) => (
            <li key={m}>{m}</li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
