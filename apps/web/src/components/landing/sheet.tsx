"use client";

/**
 * A landing section laid out like one sheet of a drawing set: "SHEET 03 / 10" rule, a large title, and the body. The
 * section fades 8 px up once it scrolls into view (useReveal); children marked `data-reveal` stagger 60 ms apart.
 */
import * as React from "react";
import { useReveal } from "@/lib/motion";
import { cn } from "@/lib/utils";

export function Sheet({
  id,
  n,
  of,
  kicker,
  title,
  description,
  actions,
  children,
  className,
}: {
  id: string;
  n: number;
  of: number;
  kicker: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  const reveal = useReveal<HTMLElement>();
  return (
    <section id={id} aria-labelledby={`${id}-title`} className={cn("scroll-mt-24 space-y-8", className)} {...reveal}>
      <header className="space-y-4">
        <div className="flex items-center gap-3 font-mono text-[10.5px] tracking-[0.16em] text-subtle uppercase">
          <span className="tnum">
            Sheet {String(n).padStart(2, "0")} / {String(of).padStart(2, "0")}
          </span>
          <span aria-hidden className="h-px flex-1 bg-border" />
          <span className="text-accent-text">{kicker}</span>
        </div>
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="max-w-3xl space-y-3">
            <h2 id={`${id}-title`} className="text-[30px] leading-[1.08] font-semibold tracking-[-0.03em] text-fg sm:text-[40px]">
              {title}
            </h2>
            {description ? <p className="max-w-2xl text-[15px] leading-7 text-muted">{description}</p> : null}
          </div>
          {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
        </div>
      </header>
      {children}
    </section>
  );
}
