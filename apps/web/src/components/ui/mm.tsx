import type { DataOrigin, ProviderMode, Source } from "@/lib/api-types";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Badge } from "./badge";
import { OriginBadge, SourceBadge } from "./provenance";

/**
 * The one way a length is shown: Geist Mono tabular numerals, always with a unit, optional ± sigma and provenance badges.
 * `source` is where the value came from; `origin`/`mode` flag synthetic inputs and mock providers.
 */
export function Mm({
  value,
  sigma,
  source,
  origin,
  mode,
  unit = "mm",
  decimals = 2,
  className,
  size = "md",
  signed = false,
}: {
  value: number | null | undefined;
  sigma?: number | null;
  source?: Source;
  origin?: DataOrigin;
  mode?: ProviderMode;
  unit?: "mm" | "deg" | "mm²" | "mm³" | "";
  decimals?: number;
  className?: string;
  size?: "sm" | "md" | "lg" | "xl";
  signed?: boolean;
}) {
  const sizes = { sm: "text-[12px]", md: "text-[13px]", lg: "text-base", xl: "text-2xl font-medium tracking-tight" } as const;
  const ok = value !== null && value !== undefined && Number.isFinite(value);
  const v = ok ? (signed && value > 0 ? "+" : signed && value < 0 ? "−" : "") + fmtNum(signed ? Math.abs(value) : value, decimals) : "—";
  const u = unit === "deg" ? "°" : unit;
  return (
    <span className={cn("inline-flex flex-wrap items-center justify-end gap-x-1.5 gap-y-1", className)}>
      <span className={cn("font-mono tnum whitespace-nowrap text-fg", sizes[size])}>
        {v}
        {ok && u ? <span className="ml-[0.25em] text-[0.85em] text-muted">{u}</span> : null}
        {ok && sigma ? (
          <span className="ml-1 text-[0.85em] text-subtle">
            ±{fmtNum(sigma, decimals)}
          </span>
        ) : null}
      </span>
      {source ? <SourceBadge source={source} /> : null}
      {origin && origin !== "real" ? <OriginBadge origin={origin} /> : null}
      {mode && mode !== "live" ? (
        <Badge tone="mock" upper>
          {mode}
        </Badge>
      ) : null}
    </span>
  );
}
