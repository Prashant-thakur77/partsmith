"use client";

/** Closing call to action, framed like the last sheet of a drawing set: registration marks, Art B and a title block. */
import { ArrowRight, FlaskConical, PenLine, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { fmtNum } from "@/lib/format";
import { useReveal } from "@/lib/motion";
import { Marker } from "../art/primitives";
import { OrthoViews } from "../art/ortho-views";
import { TitleBlock } from "../art/primitives";
import { Button } from "../ui/button";
import { useStoredRun } from "./use-figure-run";

function Corner({ className, id }: { className: string; id: number }) {
  return (
    <svg viewBox="0 0 24 24" className={`absolute size-5 ${className}`} aria-hidden>
      <Marker x={0} y={0} size={24} id={id} />
    </svg>
  );
}

export function ClosingCta({ sheet }: { sheet: { n: number; of: number } }) {
  const { fig } = useStoredRun("figure");
  const reveal = useReveal<HTMLElement>();
  const cells = {
    drawing: { k: "Drawing", v: "PartSmith" },
    scale: { k: "Scale", v: "1:1" },
    tolerance: { k: "Tolerance", v: fig?.limitMm != null ? `±${fmtNum(fig.limitMm)} mm` : "—" },
    checked: { k: "Checked by", v: "code" },
    sheet: { k: "Sheet", v: `${sheet.n} / ${sheet.of}` },
  };
  return (
    <section aria-labelledby="cta-title" className="relative rounded-2xl border border-ink/60 bg-surface p-3 shadow-sm" {...reveal}>
      <Corner className="top-3 left-3" id={31} />
      <Corner className="top-3 right-3" id={32} />
      <Corner className="bottom-3 left-3" id={33} />
      <Corner className="right-3 bottom-3" id={34} />
      <div className="rounded-xl border border-border bg-paper px-6 pt-12 pb-6 sm:px-12 sm:pt-14">
        <div className="grid grid-cols-1 items-center gap-10 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
          <div className="space-y-6">
            <p className="font-mono text-[11px] tracking-[0.16em] text-accent-text uppercase">Your turn</p>
            <h2 id="cta-title" className="text-[34px] leading-[1.04] font-semibold tracking-[-0.04em] text-fg sm:text-[48px]">
              Millions of people own a 3D printer. Almost none can design the part they need.
            </h2>
            <p className="max-w-lg text-[15.5px] leading-7 text-muted">
              Photograph the broken one on your screen. Get a program you can print, change and share, checked against your photo by code.
            </p>
            <div className="flex flex-wrap gap-2.5">
              <Button asChild variant="primary" size="lg">
                <Link href="/fix">
                  Fix a broken part <ArrowRight aria-hidden />
                </Link>
              </Button>
              <Button asChild variant="outline" size="lg">
                <Link href="/describe">
                  <PenLine aria-hidden /> Describe a part
                </Link>
              </Button>
              <Button asChild variant="ghost" size="lg">
                <Link href="/jobs/demo">
                  <FlaskConical aria-hidden /> Try a sample
                </Link>
              </Button>
              <Button asChild variant="ghost" size="lg">
                <Link href="/playground">
                  <SlidersHorizontal aria-hidden /> Playground
                </Link>
              </Button>
            </div>
          </div>
          <OrthoViews className="drop-shadow-sm" />
        </div>
        {/* phones get two rows so no cell is cut off; wider screens one row */}
        <div className="mt-10 sm:hidden">
          <TitleBlock className="rounded-t-md" cells={[cells.drawing, cells.checked]} />
          <TitleBlock className="-mt-px rounded-b-md" cells={[cells.scale, cells.tolerance, cells.sheet]} />
        </div>
        <TitleBlock className="mt-10 hidden rounded-md sm:grid" cells={[cells.drawing, cells.scale, cells.tolerance, cells.checked, cells.sheet]} />
      </div>
    </section>
  );
}
