"use client";

import { Link2, Minus, Plus, RotateCcw } from "lucide-react";
import * as React from "react";
import type { ParamSpec } from "@/lib/api-types";
import { fmtNum, paramLabel } from "@/lib/format";
import { cn, clamp, decimalsForStep, snap } from "@/lib/utils";
import { Badge } from "./badge";
import { Slider } from "./slider";
import { Tooltip } from "./tooltip";

/** One typed knob: label, live value with unit, range, "affects fit" flag; slider for dimensions, stepper for topology. */
export function Knob({
  spec,
  value,
  onChange,
  onCommit,
  disabled,
  clamped,
  compact = false,
}: {
  spec: ParamSpec;
  value: number;
  onChange: (v: number) => void;
  onCommit?: (v: number) => void;
  disabled?: boolean;
  clamped?: boolean;
  compact?: boolean;
}) {
  const id = React.useId();
  const dp = spec.topology ? 0 : decimalsForStep(spec.step);
  const unit = spec.unit === "deg" ? "°" : spec.unit;
  const [draft, setDraft] = React.useState<string | null>(null);
  const changed = Math.abs(value - spec.default) > spec.step / 2;
  const set = (v: number, commit = true) => {
    const next = snap(clamp(v, spec.min, spec.max), spec.step, spec.min);
    onChange(next);
    if (commit) onCommit?.(next);
  };
  const label = paramLabel(spec.name, spec.label);

  return (
    <div className={cn("group/knob space-y-2", disabled && "opacity-60")}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <label htmlFor={id} className="truncate text-[13px] font-medium text-fg" title={spec.name}>
            {label}
          </label>
          {spec.topology ? (
            <Tooltip content="Topology knob: changes how many features the part has, not just their size.">
              <Badge tone="accent" tabIndex={0} className="cursor-help">
                topology
              </Badge>
            </Tooltip>
          ) : null}
          {spec.affects_fit ? (
            <Tooltip content="Affects fit: changing this changes how the part fits its mating part.">
              {compact ? (
                <span tabIndex={0} role="img" aria-label="affects fit" className="inline-flex cursor-help text-subtle">
                  <Link2 className="size-3.5" aria-hidden />
                </span>
              ) : (
                <Badge tone="outline" tabIndex={0} className="cursor-help">
                  affects fit
                </Badge>
              )}
            </Tooltip>
          ) : null}
          {clamped ? (
            <Tooltip content="The server clamped this value to the knob's allowed range.">
              <Badge tone="warn" tabIndex={0} className="cursor-help">
                clamped
              </Badge>
            </Tooltip>
          ) : null}
        </div>
        <div className="flex items-center gap-1">
          {changed ? (
            <Tooltip content={`Reset to ${fmtNum(spec.default, dp)}${unit ? ` ${unit}` : ""}`}>
              <button
                type="button"
                aria-label={`Reset ${label}`}
                onClick={() => set(spec.default)}
                disabled={disabled}
                className="inline-flex size-6 items-center justify-center rounded text-subtle opacity-0 transition-opacity group-hover/knob:opacity-100 hover:bg-surface-2 hover:text-fg focus-visible:opacity-100"
              >
                <RotateCcw className="size-3" aria-hidden />
              </button>
            </Tooltip>
          ) : null}
          <div className="flex h-7 items-center rounded-md border border-border bg-surface-2 focus-within:border-ring">
            <input
              id={id}
              inputMode="decimal"
              aria-label={`${label}${unit ? ` in ${spec.unit === "deg" ? "degrees" : spec.unit === "mm" ? "millimetres" : unit}` : ""}`}
              disabled={disabled}
              value={draft ?? fmtNum(value, dp).replace(/,/g, "")}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={() => {
                if (draft !== null) {
                  const n = Number(draft);
                  if (Number.isFinite(n)) set(n);
                  setDraft(null);
                }
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                if (e.key === "Escape") setDraft(null);
              }}
              className="h-full w-16 bg-transparent px-2 text-right font-mono text-[13px] tnum text-fg outline-none"
            />
            {unit ? <span className="pr-2 font-mono text-[11px] text-subtle">{unit}</span> : null}
          </div>
        </div>
      </div>
      {spec.topology ? (
        <div className="flex items-center gap-2">
          <button
            type="button"
            aria-label={`Decrease ${label}`}
            disabled={disabled || value <= spec.min}
            onClick={() => set(value - spec.step)}
            className="inline-flex size-7 items-center justify-center rounded-md border border-border bg-surface hover:bg-surface-2 disabled:opacity-40"
          >
            <Minus className="size-3.5" aria-hidden />
          </button>
          <div className="flex flex-1 gap-1" aria-hidden>
            {Array.from({ length: Math.min(24, Math.round((spec.max - spec.min) / spec.step) + 1) }, (_, i) => spec.min + i * spec.step).map((n) => (
              <span key={n} className={cn("h-2 flex-1 rounded-[2px]", n <= value ? "bg-accent" : "bg-surface-3")} />
            ))}
          </div>
          <button
            type="button"
            aria-label={`Increase ${label}`}
            disabled={disabled || value >= spec.max}
            onClick={() => set(value + spec.step)}
            className="inline-flex size-7 items-center justify-center rounded-md border border-border bg-surface hover:bg-surface-2 disabled:opacity-40"
          >
            <Plus className="size-3.5" aria-hidden />
          </button>
        </div>
      ) : (
        <Slider
          aria-label={label}
          min={spec.min}
          max={spec.max}
          step={spec.step}
          value={[value]}
          disabled={disabled}
          onValueChange={(v) => set(v[0] ?? value, false)}
          onValueCommit={(v) => onCommit?.(v[0] ?? value)}
        />
      )}
      <div className="flex justify-between font-mono text-[11px] tnum text-subtle">
        <span>
          {fmtNum(spec.min, dp)}
          {unit ? ` ${unit}` : ""}
        </span>
        <span>
          {fmtNum(spec.max, dp)}
          {unit ? ` ${unit}` : ""}
        </span>
      </div>
    </div>
  );
}
