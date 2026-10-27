"use client";

import { RotateCcw, Zap } from "lucide-react";
import type { BakeResult, ParamSpec } from "@/lib/api-types";
import { fmtMs } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Knob } from "../ui/knob";
import { Spinner } from "../ui/spinner";

/** Knob list with bake status (cache hit / ms from the API's BakeResult). Topology knobs first. */
export function KnobPanel({
  params,
  values,
  onChange,
  bake,
  pending,
  error,
  className,
  title = "Knobs",
  dense = false,
  disabled = false,
  columns = 1,
}: {
  params: ParamSpec[];
  values: Record<string, number>;
  onChange: (next: Record<string, number>) => void;
  bake?: BakeResult | null;
  pending?: boolean;
  error?: unknown;
  className?: string;
  title?: string;
  dense?: boolean;
  disabled?: boolean;
  columns?: 1 | 2;
}) {
  const ordered = [...params].sort((a, b) => Number(b.topology) - Number(a.topology));
  const anyChanged = params.some((p) => Math.abs((values[p.name] ?? p.default) - p.default) > p.step / 2);
  return (
    <div className={cn("flex flex-col", className)}>
      <div className="flex items-center justify-between gap-2 pb-3">
        <h2 className="text-[13px] font-semibold text-fg">{title}</h2>
        <div className="flex items-center gap-1.5" aria-live="polite">
          {pending ? (
            <Badge tone="neutral" className="gap-1.5">
              <Spinner className="size-3" label="Baking" /> baking
            </Badge>
          ) : error ? (
            <Badge tone="bad">bake failed</Badge>
          ) : bake ? (
            <Badge tone={bake.cache_hit ? "ok" : "neutral"} className="font-mono tnum">
              <Zap aria-hidden />
              {bake.cache_hit ? "cache hit" : "baked"} · {fmtMs(bake.ms)}
            </Badge>
          ) : null}
          {anyChanged && !disabled ? (
            <Button
              size="icon-sm"
              variant="ghost"
              aria-label="Reset all knobs"
              title="Reset all knobs"
              onClick={() => onChange(Object.fromEntries(params.map((p) => [p.name, p.default])))}
            >
              <RotateCcw aria-hidden />
            </Button>
          ) : null}
        </div>
      </div>
      {params.length === 0 ? (
        <p className="text-[13px] text-muted">This program has no knobs.</p>
      ) : (
        <div className={cn("grid", dense ? "gap-4" : "gap-5", columns === 2 && "gap-x-8 md:grid-cols-2")}>
          {ordered.map((p) => (
            <Knob
              key={p.name}
              spec={p}
              value={values[p.name] ?? p.default}
              clamped={bake ? p.name in bake.clamped : false}
              disabled={disabled}
              compact={dense || columns === 2}
              onChange={(v) => onChange({ ...values, [p.name]: v })}
            />
          ))}
        </div>
      )}
    </div>
  );
}
