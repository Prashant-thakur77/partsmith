/**
 * Visual key for value sources: icon, patterned swatch and text label per kind, coloured with the light/dark pair from
 * `SOURCE_STYLES`. Colour is never the only cue: the label and icon always show, and each kind has its own pattern.
 */
import { BookOpen, Mic, Puzzle, Ruler, UserRound, Wand2 } from "lucide-react";
import type * as React from "react";
import { SOURCE_STYLES, swatchCss, type IconName, type SourceKind } from "@/lib/value-sources";
import { cn } from "@/lib/utils";

const ICONS: Record<IconName, typeof Ruler> = { ruler: Ruler, mic: Mic, user: UserRound, book: BookOpen, wand: Wand2, puzzle: Puzzle };

/** Inline CSS variables + classes that colour text/`currentColor` with the kind's light or dark colour. */
export function sourceColor(kind: SourceKind): { style: React.CSSProperties; className: string } {
  const s = SOURCE_STYLES[kind];
  return {
    style: { "--src-l": s.light, "--src-d": s.dark } as React.CSSProperties,
    className: "text-[var(--src-l)] dark:text-[var(--src-d)]",
  };
}

export function SourceIcon({ kind, className }: { kind: SourceKind; className?: string }) {
  const Icon = ICONS[SOURCE_STYLES[kind].icon];
  return <Icon aria-hidden className={cn("size-3.5 shrink-0", className)} />;
}

/** Small patterned square; inherits the colour of its parent (`currentColor`). Decorative: the label carries the meaning. */
export function SourceSwatch({ kind, className }: { kind: SourceKind; className?: string }) {
  return <span aria-hidden className={cn("inline-block size-3 shrink-0 rounded-[3px]", className)} style={swatchCss(SOURCE_STYLES[kind].pattern)} />;
}

/** Swatch + icon + label, coloured when `tinted`, neutral (still labelled) otherwise. */
export function SourceTag({ kind, tinted = true, className }: { kind: SourceKind; tinted?: boolean; className?: string }) {
  const c = sourceColor(kind);
  return (
    <span className={cn("inline-flex items-center gap-1 text-[11px] font-medium", tinted ? c.className : "text-muted", className)} style={tinted ? c.style : undefined}>
      <SourceSwatch kind={kind} />
      <SourceIcon kind={kind} />
      {SOURCE_STYLES[kind].label}
    </span>
  );
}

/** The legend: every kind present, with its count and one-line meaning (visible text, not a tooltip). */
export function SourceLegend({ counts, className }: { counts: { kind: SourceKind; count: number }[]; className?: string }) {
  if (!counts.length) return null;
  return (
    <ul aria-label="Colour key: where each value came from" className={cn("grid gap-x-4 gap-y-1.5 sm:grid-cols-2", className)}>
      {counts.map(({ kind, count }) => (
        <li key={kind} className="flex min-w-0 items-start gap-2 text-[12px] leading-4">
          <SourceTag kind={kind} className="mt-px shrink-0" />
          <span className="font-mono text-[11px] text-subtle tnum" aria-label={`${count} value${count === 1 ? "" : "s"}`}>
            {count}
          </span>
          <span className="min-w-0 text-muted">{SOURCE_STYLES[kind].description}</span>
        </li>
      ))}
    </ul>
  );
}
