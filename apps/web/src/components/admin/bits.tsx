"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { shares } from "@/lib/api-admin";
import { cn } from "@/lib/utils";

/** A number with what it counts, its n and where it comes from. */
export function Stat({ label, value, sub, source }: { label: string; value: React.ReactNode; sub?: React.ReactNode; source: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-surface p-4">
      <p className="text-[12px] text-muted">{label}</p>
      <p className="mt-1 text-[22px] font-semibold tracking-tight text-fg tnum">{value}</p>
      {sub ? <p className="mt-0.5 text-[12px] text-muted tnum">{sub}</p> : null}
      <p className="mt-2 text-[11px] leading-4 text-subtle">From {source}</p>
    </div>
  );
}

/** A card with a title, a body and a source line. */
export function Panel({ title, source, children, className }: { title: string; source?: string; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("min-w-0 space-y-3 rounded-lg border border-border bg-surface p-4", className)} aria-label={title}>
      <h2 className="text-[14px] font-semibold text-fg">{title}</h2>
      {children}
      {source ? <p className="text-[11px] leading-4 text-subtle">From {source}</p> : null}
    </section>
  );
}

/** Horizontal bars, widths relative to the largest value. Values are shown as text too (the bar is decoration). */
export function Bars({ rows, label }: { rows: { key: string; label: React.ReactNode; value: number; text: string }[]; label: string }) {
  const w = shares(rows.map((r) => r.value));
  return (
    <ul className="space-y-2" aria-label={label}>
      {rows.map((r, i) => (
        <li key={r.key} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 text-[13px]">
          <span className="min-w-0 truncate text-fg">{r.label}</span>
          <span className="text-muted tnum">{r.text}</span>
          <span className="col-span-2 h-1.5 overflow-hidden rounded-full bg-surface-2" aria-hidden>
            <span className="block h-full rounded-full bg-accent" style={{ width: `${Math.round((w[i] ?? 0) * 100)}%` }} />
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Ask for a reason before an admin action; the reason goes to the audit log. */
export function ReasonForm({
  label,
  confirm,
  busy,
  onSubmit,
  onCancel,
  danger = false,
}: {
  label: string;
  confirm: string;
  busy: boolean;
  onSubmit: (reason: string) => void;
  onCancel: () => void;
  danger?: boolean;
}) {
  const [reason, setReason] = React.useState("");
  const id = React.useId();
  return (
    <form
      className="flex flex-col gap-2 rounded-md border border-border bg-surface-2 p-3 sm:flex-row sm:items-end"
      onSubmit={(e) => {
        e.preventDefault();
        if (reason.trim()) onSubmit(reason.trim());
      }}
    >
      <div className="min-w-0 flex-1 space-y-1">
        <label htmlFor={id} className="block text-[12px] text-muted">
          {label}
        </label>
        <Input id={id} value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} autoFocus placeholder="A short reason" />
      </div>
      <div className="flex gap-2">
        <Button type="submit" size="sm" variant={danger ? "danger" : "outline"} disabled={!reason.trim() || busy}>
          {confirm}
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
