"use client";

/**
 * Buy or print, for the recorded run on Fig. 1: the cheapest cited offer the web search found (with its link) next to
 * the code's own print estimate (grams, minutes, filament cost). Read from `/jobs/{id}/buy-or-print`; a price is shown
 * only with its source link, and the whole card is labelled with the part and where its numbers came from.
 */
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Printer, ShoppingCart } from "lucide-react";
import * as React from "react";
import { api } from "@/lib/api";
import { decimalsOf } from "@/lib/count-up";
import { citedOem, citedOffers, costEntries, hostOf, lookupState, money } from "@/lib/buy-or-print";
import { fmtNum, splitTitle } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { ErrorState } from "../ui/error-state";
import { CountUp } from "../ui/count-up";
import { Skeleton } from "../ui/skeleton";
import { useStoredRun } from "./use-figure-run";

function Big({ text, unit, className }: { text: string; unit?: string; className?: string }) {
  return (
    <div className={cn("flex items-baseline gap-1.5", className)}>
      <CountUp text={text} unitClassName="ml-1 text-[0.4em] tracking-normal text-muted" className="font-mono text-[40px] leading-none font-medium tracking-[-0.04em] text-fg sm:text-[48px]" />
      {unit ? <span className="font-mono text-[13px] text-muted">{unit}</span> : null}
    </div>
  );
}

export function BuyOrPrintStrip() {
  const { pick, fig, replays } = useStoredRun("figure");
  const q = useQuery({ queryKey: ["buy-or-print", pick?.id], queryFn: () => api.jobBuyOrPrint(pick!.id), enabled: !!pick, retry: false, staleTime: 300_000 });
  const card = q.data;
  const offers = citedOffers(card?.lookup).sort((a, b) => a.price - b.price);
  const best = offers[0];
  const oem = citedOem(card?.lookup);
  const pla = card?.prints.find((p) => p.material.toUpperCase() === "PLA") ?? card?.prints[0];
  const costs = pla ? costEntries(pla) : [];
  const state = lookupState(card);
  const title = card?.title || (fig ? splitTitle(fig.title).title : "");

  if (replays.isError) return <ErrorState error={replays.error} compact what="the recorded runs" onRetry={() => void replays.refetch()} />;
  if (!pick || q.isPending) return replays.data && !pick ? <p className="text-[13.5px] text-muted">No stored run on this server yet.</p> : <Skeleton className="h-64" />;
  if (q.isError || !card)
    return (
      <p className="rounded-xl border border-dashed border-border-strong bg-surface px-5 py-6 text-[13.5px] text-muted">
        This server has no buy-or-print record for the recorded run yet, so there is nothing to compare here.
      </p>
    );

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 overflow-hidden rounded-xl border border-border bg-surface md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]">
        <section aria-label="Buy" className="flex flex-col gap-4 p-6 sm:p-7" data-reveal>
          <div className="flex items-center gap-2 font-mono text-[11px] tracking-[0.14em] text-subtle uppercase">
            <ShoppingCart className="size-3.5" aria-hidden /> Buy the original
          </div>
          {best ? (
            <>
              <Big text={money(best.price, best.currency)} />
              <p className="text-[13.5px] leading-6 text-muted">
                Cheapest of {offers.length} cited {offers.length === 1 ? "offer" : "offers"}
                {best.availability ? <> · {best.availability.toLowerCase()}</> : null}
                {oem ? (
                  <>
                    {" "}· part <span className="font-mono text-fg">{oem.number || oem.name}</span>
                  </>
                ) : null}
              </p>
              <a href={best.href} target="_blank" rel="noreferrer noopener" className="inline-flex w-fit items-center gap-1 font-mono text-[12px] text-accent-text hover:underline">
                {hostOf(best.href)} <ArrowUpRight className="size-3.5" aria-hidden />
                <span className="sr-only">(opens the cited page)</span>
              </a>
            </>
          ) : (
            <p className="text-[14px] leading-6 text-muted">
              {state === "searched" ? "The web search found no price it could cite for this part." : state === "mock" ? "Only a mock lookup is stored for this run (no real prices)." : "No price lookup is stored for this run."}
            </p>
          )}
        </section>
        <div aria-hidden className="relative hidden items-center md:flex">
          <span className="h-full w-px bg-border" />
          <span className="absolute left-1/2 -translate-x-1/2 rounded-full border border-border bg-bg px-2 py-1 font-mono text-[11px] text-subtle">or</span>
        </div>
        <section aria-label="Print" className="flex flex-col gap-4 border-t border-border p-6 sm:p-7 md:border-t-0" data-reveal style={{ "--reveal-i": 1 } as React.CSSProperties}>
          <div className="flex items-center gap-2 font-mono text-[11px] tracking-[0.14em] text-subtle uppercase">
            <Printer className="size-3.5" aria-hidden /> Print the verified program
          </div>
          {pla ? (
            <>
              <div className="flex flex-wrap items-end gap-x-6 gap-y-2">
                <Big text={fmtNum(pla.grams, decimalsOf(String(pla.grams)))} unit={`g ${pla.material}`} />
                {pla.print_minutes != null ? <Big text={fmtNum(pla.print_minutes, decimalsOf(String(pla.print_minutes)))} unit="min" /> : null}
              </div>
              <p className="text-[13.5px] leading-6 text-muted">
                Filament {costs.length ? costs.slice(0, 2).map((c) => money(c.amount, c.currency)).join(" / ") : "cost not estimated"} at an assumed spool price. Solid volume, so a real print weighs less; the assumptions are on the run&apos;s page.
              </p>
            </>
          ) : (
            <p className="text-[14px] text-muted">No print estimate is stored for this run.</p>
          )}
        </section>
      </div>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11px] leading-4 text-subtle">
        <span className="text-fg">{title}</span>
        <Badge tone="mock">recorded run</Badge>
        <span>· buy: {card.lookup?.label || "web lookup"} ({card.lookup?.mode ?? card.mode})</span>
        <span>· print: code&apos;s estimate from the model&apos;s volume</span>
      </p>
    </div>
  );
}
