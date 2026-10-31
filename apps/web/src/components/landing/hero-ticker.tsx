"use client";

/**
 * A mono readout above the hero headline, built only from API numbers: the synthetic bench's median size error and,
 * beside it, how many of the same cases passed verification (both `/bench`, labelled synthetic, with n), the runs
 * listed on /jobs (`/stats`: listed = made here + recorded, both named) and the lying-model attacks code blocked (bench evidence). An item is left out
 * while its source is missing — never a placeholder number.
 */
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { api } from "@/lib/api";
import type { BenchReport, Stats } from "@/lib/api-types";
import { benchHeadline, benchVerified } from "@/lib/bench";
import { ERROR_LIMIT_MM, fmtInt } from "@/lib/format";
import { RUN_WORDS, runCounts, runSplitText } from "@/lib/page-groups";
import { cn } from "@/lib/utils";
import { CountUp } from "../ui/count-up";

type Item = { k: string; v: string; note?: string; href: string };

/** The same count `/jobs` lists, in the shared words: runs listed = made here + recorded. */
function runsItem(stats: Stats): Item {
  const c = runCounts(stats);
  return { k: `${c.listed === 1 ? "run" : "runs"} ${RUN_WORDS.listed}`, v: fmtInt(c.listed), note: runSplitText(c), href: "/jobs" };
}

export function tickerItems(stats?: Stats | null, bench?: BenchReport | null): Item[] {
  const out: Item[] = [];
  const syn = bench?.tables.synthetic;
  const head = syn ? benchHeadline(syn) : null;
  if (syn && head && /median/.test(head.gt)) out.push({ k: "median size error", v: head.value, note: `n = ${head.n} · synthetic`, href: "/results#synthetic" });
  const ver = benchVerified(syn);
  // the strict rate: a case counts only when every check is inside the limit (the server's own jobs are on /jobs)
  if (ver) out.push({ k: "passed verification", v: `${ver.passed}/${ver.n}`, note: `strict: every check ≤ ${ERROR_LIMIT_MM} mm · same cases`, href: "/results#synthetic" });
  if (stats) out.push(runsItem(stats));
  const by = bench?.evidence?.bypass;
  if (by) out.push({ k: "lying-model attacks blocked", v: `${by.blocked}/${by.attempts}`, note: "scripted", href: "/judges" });
  return out;
}

export function HeroTicker({ stats: initialStats, bench: initialBench }: { stats?: Stats | null; bench?: BenchReport | null }) {
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats, initialData: initialStats ?? undefined, initialDataUpdatedAt: 0, retry: false });
  const bench = useQuery({ queryKey: ["bench"], queryFn: api.bench, initialData: initialBench ?? undefined, initialDataUpdatedAt: 0, retry: false, staleTime: 300_000 });
  const items = tickerItems(stats.data, bench.data);
  const live = stats.isSuccess;
  return (
    <div className="flex max-w-full items-stretch overflow-hidden rounded-md border border-border bg-surface/80 font-mono text-[11.5px] leading-none shadow-sm backdrop-blur-sm">
      <span className="flex shrink-0 items-center gap-1.5 border-r border-border px-2.5 py-2 text-[10px] tracking-[0.14em] text-subtle uppercase">
        <span className={live ? "size-1.5 rounded-full bg-ok motion-safe:animate-[pulse-dot_1.6s_ease-in-out_3]" : "size-1.5 rounded-full bg-border-strong"} aria-hidden />
        <span className="sr-only sm:not-sr-only">{live ? "This server" : "Connecting"}</span>
      </span>
      {/* phones: a 2-column grid, every item whole (text wraps); wider screens: one wrapping row */}
      <ul className="grid min-w-0 flex-1 grid-cols-2 sm:flex sm:flex-wrap" aria-label="Numbers from this server">
        {items.length === 0 ? (
          <li className="col-span-2 px-3 py-2 text-subtle">reading /stats and /bench…</li>
        ) : (
          items.map((it, i) => (
            <li
              key={it.k}
              className={cn(
                "flex min-w-0 border-border",
                i % 2 === 1 && "border-l",
                i > 1 && "border-t sm:border-t-0",
                i > 0 && "sm:border-l",
                items.length % 2 === 1 && i === items.length - 1 && "col-span-2 sm:col-span-1",
              )}
            >
              <a href={it.href} className="press flex min-w-0 flex-1 flex-col gap-1 px-3 py-2 hover:bg-surface-2 sm:flex-row sm:items-baseline sm:gap-1.5 sm:whitespace-nowrap">
                <CountUp text={it.v} className="font-semibold text-fg" />
                <span className="leading-tight text-muted">{it.k}</span>
                {it.note ? <span className="leading-tight text-subtle">({it.note})</span> : null}
              </a>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
