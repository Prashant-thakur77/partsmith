"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/** Pressed/unpressed button (aria-pressed). */
export function Toggle({
  className,
  pressed,
  onPressedChange,
  ...props
}: Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onChange"> & { pressed: boolean; onPressedChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      data-state={pressed ? "on" : "off"}
      onClick={() => onPressedChange(!pressed)}
      className={cn(
        "inline-flex h-8 items-center justify-center gap-1.5 rounded-md px-2 text-[12px] font-medium text-muted transition-[color,background-color,border-color,transform] duration-[var(--dur-hover)] ease-[var(--ease-out)] active:scale-[0.97] hover:bg-surface-2 hover:text-fg data-[state=on]:bg-surface-3 data-[state=on]:text-fg [&_svg]:size-4",
        className,
      )}
      {...props}
    />
  );
}

/** Accessible on/off switch (role="switch"). */
export function Switch({
  checked,
  onCheckedChange,
  label,
  className,
  id,
}: {
  checked: boolean;
  onCheckedChange: (v: boolean) => void;
  label: string;
  className?: string;
  id?: string;
}) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onCheckedChange(!checked)}
      className={cn("group inline-flex items-center gap-2 text-[13px] text-fg", className)}
    >
      <span
        className={cn(
          "relative inline-flex h-[18px] w-[30px] shrink-0 items-center rounded-full border transition-colors",
          checked ? "border-transparent bg-accent" : "border-border-strong bg-surface-3",
        )}
      >
        <span className={cn("absolute size-3.5 rounded-full bg-white shadow-sm transition-transform", checked ? "translate-x-[13px]" : "translate-x-[1px]")} />
      </span>
      {label}
    </button>
  );
}
