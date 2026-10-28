"use client";

import { Download, Lock, Printer } from "lucide-react";
import * as React from "react";
import type { ShipState } from "@/lib/ship";
import { slicerHandoff } from "@/lib/slicers";
import { useOrigin } from "@/lib/use-origin";
import { cn } from "@/lib/utils";

/**
 * "Open in slicer" for the part's 3MF, under the export gate: hidden when blocked, waiting for the acknowledgement when
 * best effort, otherwise one deep link per slicer that accepts a web URL and download + instructions for the others.
 */
export function OpenInSlicer({ fileUrl, ship, ack, className }: { fileUrl: string | null | undefined; ship: ShipState; ack: boolean; className?: string }) {
  const origin = useOrigin();
  const h = slicerHandoff(fileUrl, origin, ship, ack);
  const [picked, setPicked] = React.useState<string | null>(null);
  const headingId = React.useId();
  if (h.state === "hidden") return null;
  const note = h.state === "ready" ? h.links.find((l) => l.slicer.id === picked)?.slicer.howTo : null;
  return (
    <div role="group" aria-labelledby={headingId} className={cn("space-y-2", className)}>
      <div id={headingId} className="flex items-center gap-1.5 text-[12px] font-medium text-muted">
        <Printer className="size-3.5" aria-hidden /> Open the 3MF in a slicer
      </div>
      {h.state === "needs_ack" ? (
        <p className="flex items-center gap-1.5 text-[12px] text-muted">
          <Lock className="size-3.5 shrink-0" aria-hidden /> Available after you acknowledge the best-effort notice.
        </p>
      ) : (
        <>
          <div className="flex flex-wrap gap-1.5">
            {h.links.map(({ slicer, href }) =>
              href ? (
                <a
                  key={slicer.id}
                  href={href}
                  onClick={() => setPicked(slicer.id)}
                  className="inline-flex h-8 items-center rounded-md border border-border bg-surface px-2.5 text-[12.5px] font-medium hover:border-border-strong hover:bg-surface-2"
                >
                  {slicer.name}
                </a>
              ) : (
                <a
                  key={slicer.id}
                  href={h.fileUrl}
                  download
                  onClick={() => setPicked(slicer.id)}
                  className="inline-flex h-8 items-center gap-1 rounded-md border border-border bg-surface px-2.5 text-[12.5px] font-medium hover:border-border-strong hover:bg-surface-2"
                  aria-describedby={`${headingId}-${slicer.id}`}
                >
                  <Download className="size-3.5" aria-hidden /> {slicer.name}
                  <span id={`${headingId}-${slicer.id}`} className="sr-only">
                    : {slicer.howTo}
                  </span>
                </a>
              ),
            )}
          </div>
          <p className="text-[11.5px] leading-5 text-subtle" aria-live="polite">
            {note ?? "Your browser asks before it opens the app. The slicer downloads the file from this site."}
          </p>
        </>
      )}
    </div>
  );
}
