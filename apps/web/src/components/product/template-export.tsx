"use client";

import { Box, Download, FileCode2, Layers, ShieldAlert } from "lucide-react";
import * as React from "react";
import { productApi } from "@/lib/api-product";
import { cn } from "@/lib/utils";

const FILES = [
  { f: "stl", label: "STL", sub: "mesh for any slicer", icon: Box },
  { f: "3mf", label: "3MF", sub: "with print settings", icon: Layers },
  { f: "step", label: "STEP", sub: "editable in any CAD", icon: Box },
  { f: "py", label: "part.py", sub: "the program at these values", icon: FileCode2 },
] as const;

/** The export gate for template files, as the server applies it: nothing compared them with a real part, so printable
 * files need an explicit acknowledgement first (the program itself is always open). */
export function useTemplateAck() {
  const [ack, setAck] = React.useState(false);
  return { ack, setAck };
}

export function TemplateAckNotice({ ack, onAck, reason, className }: { ack: boolean; onAck: (v: boolean) => void; reason: string; className?: string }) {
  const id = React.useId();
  return (
    <div className={cn("space-y-2 rounded-lg border border-warn-border bg-warn-soft p-3 text-[12.5px]", className)} role="note">
      <p className="flex items-start gap-2 text-fg">
        <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
        <span>{reason}</span>
      </p>
      <label htmlFor={id} className="flex cursor-pointer items-start gap-2 text-fg">
        <input id={id} type="checkbox" checked={ack} onChange={(e) => onAck(e.target.checked)} className="mt-0.5 size-4 accent-[var(--accent)]" />
        I understand: these files are not checked against a real part.
      </label>
    </div>
  );
}

export function TemplateExport({ template, values, ack, className }: { template: string; values: Record<string, number>; ack: boolean; className?: string }) {
  return (
    <div className={cn("space-y-1.5", className)} aria-label="Export files">
      {FILES.map((d) => {
        const locked = d.f !== "py" && !ack;
        return (
          <a
            key={d.f}
            href={locked ? undefined : productApi.templateDownloadUrl(template, values, d.f)}
            aria-disabled={locked || undefined}
            tabIndex={locked ? -1 : undefined}
            download
            className={cn(
              "flex items-center gap-3 rounded-md border border-border px-3 py-2 text-[13px] transition-colors hover:border-border-strong hover:bg-surface-2",
              locked && "pointer-events-none opacity-45",
            )}
          >
            <d.icon className="size-4 text-muted" aria-hidden />
            <span className="flex-1">
              <span className="font-medium">{d.label}</span> <span className="text-subtle">· {d.sub}</span>
            </span>
            <Download className="size-3.5 text-subtle" aria-hidden />
          </a>
        );
      })}
    </div>
  );
}
