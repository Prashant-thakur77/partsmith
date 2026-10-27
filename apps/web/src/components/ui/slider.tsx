"use client";

/**
 * Range slider on a native `<input type="range">` (keyboard, screen readers and touch for free), styled with CSS.
 * API mirrors the subset of the previous Radix slider we use: value as a one-element array, change and commit callbacks.
 */
import * as React from "react";
import { cn } from "@/lib/utils";

export function Slider({
  className,
  value,
  defaultValue,
  min = 0,
  max = 100,
  step = 1,
  disabled,
  onValueChange,
  onValueCommit,
  "aria-label": ariaLabel,
  "aria-valuetext": ariaValueText,
}: {
  className?: string;
  value?: number[];
  defaultValue?: number[];
  min?: number;
  max?: number;
  step?: number;
  disabled?: boolean;
  onValueChange?: (v: number[]) => void;
  onValueCommit?: (v: number[]) => void;
  "aria-label"?: string;
  "aria-valuetext"?: string;
}) {
  const v = value?.[0] ?? defaultValue?.[0] ?? min;
  const pct = max > min ? ((v - min) / (max - min)) * 100 : 0;
  const commit = (e: React.SyntheticEvent<HTMLInputElement>) => onValueCommit?.([Number(e.currentTarget.value)]);
  return (
    <input
      type="range"
      min={min}
      max={max}
      step={step}
      value={v}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-valuetext={ariaValueText}
      onChange={(e) => onValueChange?.([Number(e.currentTarget.value)])}
      onPointerUp={commit}
      onKeyUp={commit}
      className={cn("ps-range h-5 w-full cursor-pointer disabled:cursor-not-allowed disabled:opacity-50", className)}
      style={{ "--pct": `${pct}%` } as React.CSSProperties}
    />
  );
}
