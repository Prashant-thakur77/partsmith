"use client";

/** "Sizes the photo can't see": up to four named sizes (inner bore Ø, socket depth …) the user knows, in mm. */
import { Plus, X } from "lucide-react";
import * as React from "react";
import { HIDDEN_KINDS, MAX_HIDDEN, type HiddenRow } from "@/lib/hidden-dims";
import { cn } from "@/lib/utils";
import { Button } from "../ui/button";
import { Input, Label, Select } from "../ui/input";

export function HiddenDimsField({ rows, onChange, problems }: { rows: HiddenRow[]; onChange: (rows: HiddenRow[]) => void; problems: Record<number, string> }) {
  const id = React.useId();
  const set = (i: number, patch: Partial<HiddenRow>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <fieldset className="space-y-2 sm:col-span-2" aria-describedby={`${id}-help`}>
      <legend className="text-[13px] font-medium text-fg">Sizes the photo can&apos;t see</legend>
      <p id={`${id}-help`} className="text-[12px] text-subtle">
        Optional. A bore inside, how deep a socket goes. The builder must use these numbers; code checks them against the
        program where a knob holds them. They are your numbers, not measured, so they never count towards verified.
      </p>
      {rows.map((r, i) => (
        <div key={i} className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <Label htmlFor={`${id}-k${i}`} className="sr-only">
              Which size {i + 1}
            </Label>
            <Select id={`${id}-k${i}`} value={r.kind} onChange={(e) => set(i, { kind: e.target.value })} className="h-9 min-w-[11rem] flex-1 sm:flex-none">
              {HIDDEN_KINDS.map((k) => (
                <option key={k.name} value={k.name}>
                  {k.label}
                </option>
              ))}
              <option value="other">Other (your words)</option>
            </Select>
            {r.kind === "other" ? (
              <>
                <Label htmlFor={`${id}-o${i}`} className="sr-only">
                  Name of size {i + 1}
                </Label>
                <Input id={`${id}-o${i}`} value={r.other} maxLength={40} onChange={(e) => set(i, { other: e.target.value })} placeholder="e.g. lip depth" className="h-9 w-40" />
              </>
            ) : null}
            <Label htmlFor={`${id}-v${i}`} className="sr-only">
              Size {i + 1} in millimetres
            </Label>
            <div className="relative">
              <Input
                id={`${id}-v${i}`}
                inputMode="decimal"
                value={r.value}
                onChange={(e) => set(i, { value: e.target.value })}
                placeholder="mm"
                aria-invalid={problems[i] ? true : undefined}
                aria-describedby={problems[i] ? `${id}-p${i}` : undefined}
                className={cn("h-9 w-28 pr-9 font-mono tnum", problems[i] && "border-bad")}
              />
              <span className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 font-mono text-[12px] text-subtle">mm</span>
            </div>
            <Button type="button" variant="ghost" size="sm" onClick={() => onChange(rows.filter((_, j) => j !== i))} aria-label={`Remove size ${i + 1}`}>
              <X aria-hidden />
            </Button>
          </div>
          {problems[i] ? (
            <p id={`${id}-p${i}`} className="text-[12px] text-bad">
              {problems[i]}
            </p>
          ) : null}
        </div>
      ))}
      {rows.length < MAX_HIDDEN ? (
        <Button type="button" variant="outline" size="sm" onClick={() => onChange([...rows, { kind: "bore_d", other: "", value: "" }])}>
          <Plus aria-hidden /> Add a size
        </Button>
      ) : null}
    </fieldset>
  );
}
