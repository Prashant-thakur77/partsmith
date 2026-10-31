/** The sizes the user stated because the photo cannot show them, and how code checked each against the program. */
import type { HiddenDimRow } from "@/lib/api-types";
import { fmtNum } from "@/lib/format";
import { hiddenStatusText } from "@/lib/hidden-dims";
import { cn } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { Eyebrow } from "../ui/card";

const TONE = { checked: "info", mismatch: "bad", used_not_checked: "neutral", pending: "neutral" } as const;

export function HiddenDimsCard({ rows, className }: { rows: readonly HiddenDimRow[]; className?: string }) {
  if (!rows.length) return null;
  return (
    <section className={cn("space-y-2 rounded-lg border border-border bg-surface p-4", className)} aria-label="Sizes you gave" data-testid="hidden-dims">
      <Eyebrow>Sizes you gave (not measured)</Eyebrow>
      <ul className="space-y-2 text-[12.5px]">
        {rows.map((r, i) => (
          <li key={`${r.name}-${i}`} className="space-y-0.5">
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <span className="font-medium text-fg">{r.label}</span>
              <span className="font-mono tnum">{fmtNum(r.value_mm)} mm</span>
              <Badge tone={TONE[r.status]}>{hiddenStatusText(r.status)}</Badge>
            </div>
            {r.note ? <p className="text-[11.5px] leading-4 text-muted">{r.note}</p> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
