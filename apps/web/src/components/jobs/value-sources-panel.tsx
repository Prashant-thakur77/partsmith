"use client";

/**
 * "Where each value came from": the list of every value the job measured or used, grouped, each selectable with the
 * keyboard, and a detail panel for the selected one (value ± σ, source, evidence note, the photo or overlay it came
 * from, and whether any test compared it with a photo). The same selection drives the 3D callouts in the viewer, so
 * this list is also the keyboard and screen-reader route to them. Only copies numbers from the job detail.
 */
import { Box, ExternalLink, EyeOff, List, X } from "lucide-react";
import * as React from "react";
import { artifactUrl } from "@/lib/api";
import { boundText } from "@/lib/evidence-notes";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";
import { SOURCE_STYLES, checkText, kindCounts, valueText, type ValueItem } from "@/lib/value-sources";
import { Badge } from "../ui/badge";
import { Switch } from "../ui/toggle";
import { SourceLegend, SourceTag, sourceColor } from "./source-key";

const GROUPS: { group: ValueItem["group"]; title: string }[] = [
  { group: "dimension", title: "Overall sizes" },
  { group: "feature", title: "Features" },
  { group: "region", title: "Rebuilt region" },
  { group: "knob", title: "Knobs no test checked" },
];

export function ValueSourcesPanel({
  items,
  tinted,
  onTint,
  selectedId,
  onSelect,
  inViewer,
  className,
}: {
  items: ValueItem[];
  tinted: boolean;
  onTint: (v: boolean) => void;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  /** True when the viewer has geometry to draw anchored values on. */
  inViewer: boolean;
  className?: string;
}) {
  const titleId = React.useId();
  const detailId = React.useId();
  const selected = items.find((i) => i.id === selectedId) ?? null;
  const counts = React.useMemo(() => kindCounts(items), [items]);
  if (!items.length) return null;
  return (
    <section aria-labelledby={titleId} className={cn("space-y-3", className)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={titleId} className="text-[11px] font-medium tracking-[0.08em] text-subtle uppercase">
          Where each value came from
        </h2>
        <Switch checked={tinted} onCheckedChange={onTint} label="Colour by source" className="text-[12px]" />
      </div>
      {tinted ? <SourceLegend counts={counts} /> : null}

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="scrollbar-thin max-h-[300px] space-y-3 overflow-y-auto pr-1">
          {GROUPS.map(({ group, title }) => {
            const rows = items.filter((i) => i.group === group);
            if (!rows.length) return null;
            return (
              <div key={group} className="space-y-1">
                <h3 className="text-[11.5px] font-medium text-muted">{title}</h3>
                <ul className="space-y-0.5">
                  {rows.map((i) => {
                    const c = sourceColor(i.kind);
                    const on = i.id === selectedId;
                    return (
                      <li key={i.id}>
                        <button
                          type="button"
                          aria-pressed={on}
                          aria-controls={detailId}
                          onClick={() => onSelect(on ? null : i.id)}
                          className={cn(
                            "flex w-full flex-wrap items-center gap-x-2 gap-y-0.5 rounded-md border-l-[3px] px-2 py-1 text-left text-[12.5px] hover:bg-surface-2",
                            tinted ? c.className : "border-l-border",
                            on && "bg-surface-2 ring-1 ring-border-strong",
                          )}
                          style={tinted ? { ...c.style, borderLeftColor: "currentColor", borderLeftStyle: SOURCE_STYLES[i.kind].dash === "solid" ? "solid" : SOURCE_STYLES[i.kind].dash } : undefined}
                        >
                          <span className="min-w-0 flex-1 truncate text-fg">{i.label}</span>
                          <span className="shrink-0 font-mono text-[12px] text-fg tnum">{valueText(i)}</span>
                          <SourceTag kind={i.kind} tinted={tinted} className="shrink-0" />
                          {i.unchecked ? (
                            <span className="inline-flex shrink-0 items-center text-warn">
                              <EyeOff className="size-3.5" aria-hidden />
                              <span className="sr-only">, not checked against a photo</span>
                            </span>
                          ) : null}
                          {inViewer && i.anchor ? <Box className="size-3.5 shrink-0 text-subtle" aria-hidden /> : <List className="size-3.5 shrink-0 text-subtle" aria-hidden />}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-subtle">
            <span className="inline-flex items-center gap-1">
              <Box className="size-3" aria-hidden /> drawn on the 3D model when Colour by source is on
            </span>
            <span className="inline-flex items-center gap-1">
              <List className="size-3" aria-hidden /> list only (no geometry to point at)
            </span>
            <span className="inline-flex items-center gap-1">
              <EyeOff className="size-3 text-warn" aria-hidden /> not checked against a photo
            </span>
          </p>
        </div>

        <div id={detailId} role="region" aria-live="polite" aria-label="Selected value" className="min-w-0">
          {selected ? <ValueDetail item={selected} tinted={tinted} onClose={() => onSelect(null)} /> : (
            <p className="rounded-md border border-dashed border-border px-3 py-4 text-center text-[12px] text-muted">
              Select a value here or a callout on the model to see where it came from.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

function ValueDetail({ item, tinted, onClose }: { item: ValueItem; tinted: boolean; onClose: () => void }) {
  const s = SOURCE_STYLES[item.kind];
  const bound = boundText(item.boundMm);
  return (
    <div
      className="space-y-2 rounded-md border border-border bg-surface-2 p-3 text-[12.5px]"
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="font-medium text-fg">{item.label}</h3>
          <p className="font-mono text-[15px] text-fg tnum">{valueText(item)}</p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close value details" className="inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted hover:bg-surface-3 hover:text-fg">
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <div className="space-y-0.5">
        <SourceTag kind={item.kind} tinted={tinted} className="text-[12px]" />
        <p className="text-muted">{s.description}</p>
      </div>
      {bound ? <p className="font-mono text-[11.5px] text-warn tnum">{bound}</p> : null}
      {item.note ? (
        <p className="text-muted">
          <span className="text-subtle">Evidence: </span>
          {item.note}
        </p>
      ) : null}
      <p className={cn("flex items-start gap-1.5", item.unchecked ? "font-medium text-warn" : "text-muted")}>
        {item.unchecked ? <EyeOff className="mt-0.5 size-3.5 shrink-0" aria-hidden /> : null}
        {checkText(item)}
      </p>
      {item.residuals.length ? (
        <div className="relative max-w-full overflow-x-auto">
        <table className="w-full font-mono text-[11.5px] tnum">
          <caption className="sr-only">Verifier residuals for {item.label}, millimetres</caption>
          <thead>
            <tr className="text-left text-[10.5px] text-subtle">
              <th scope="col" className="py-0.5 font-sans font-medium">Check</th>
              <th scope="col" className="py-0.5 text-right font-sans font-medium">Photo</th>
              <th scope="col" className="py-0.5 text-right font-sans font-medium">Model</th>
              <th scope="col" className="py-0.5 text-right font-sans font-medium">Δ (tol)</th>
              <th scope="col" className="py-0.5 text-right font-sans font-medium">Result</th>
            </tr>
          </thead>
          <tbody>
            {item.residuals.map((r) => (
              <tr key={`${r.feature_id}.${r.quantity}`} className="border-t border-border">
                <th scope="row" className="py-1 text-left font-sans font-normal text-muted">{r.quantity.replaceAll("_", " ")}</th>
                <td className="py-1 text-right">{fmtNum(r.measured_mm)}</td>
                <td className="py-1 text-right">{fmtNum(r.model_mm)}</td>
                <td className="py-1 text-right">
                  {r.delta_mm >= 0 ? "+" : "−"}
                  {fmtNum(Math.abs(r.delta_mm))} (±{fmtNum(r.tol_mm)})
                </td>
                <td className="py-1 text-right">
                  <Badge tone={r.passed ? "ok" : "bad"}>{r.passed ? "within" : "out"}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      ) : null}
      {item.citation ? (
        <a href={item.citation.url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-accent-text hover:underline">
          <ExternalLink className="size-3.5" aria-hidden /> {item.citation.title || item.citation.url}
        </a>
      ) : null}
      {item.evidence.length ? (
        <ul className="space-y-0.5" aria-label="Where it came from">
          {item.evidence.map((e) => (
            <li key={e.url}>
              <a href={artifactUrl(e.url)} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-[12px] text-accent-text hover:underline">
                <ExternalLink className="size-3.5 shrink-0" aria-hidden /> {e.label}
              </a>
            </li>
          ))}
        </ul>
      ) : item.kind === "user_stated" ? (
        <p className="text-[12px] text-subtle">From your own words; there is no photo for it.</p>
      ) : null}
    </div>
  );
}
