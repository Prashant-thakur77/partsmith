"use client";

/**
 * A mono readout above the hero headline, built only from API numbers: the synthetic bench's median size error and,
 * beside it, how many of the same cases passed verification (both `/bench`, labelled synthetic, with n), the runs
 * stored on this server (`/stats`) and the lying-model attacks code blocked (bench evidence). An item is left out
 * while its source is missing — never a placeholder number.
 */
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { api } from "@/lib/api";
import type { BenchReport, Stats } from "@/lib/api-types";
import { benchHeadline, benchVerified } from "@/lib/bench";
import { fmtInt } from "@/lib/format";
import { CountUp } from "../ui/count-up";

type Item = { k: string; v: string; note?: string; href: string };

export function tickerItems(stats?: Stats | null, bench?: BenchReport | null): Item[] {
  const out: Item[] = [];
  const syn = bench?.tables.synthetic;
  const head = syn ? benchHeadline(syn) : null;
  if (syn && head && /median/.test(head.gt)) out.push({ k: "median size error", v: head.value, note: `n = ${head.n} · synthetic`, href: "/results#synthetic" });
  const ver = benchVerified(syn);
  if (ver) out.push({ k: "passed verification", v: `${ver.passed}/${ver.n}`, note: "same synthetic cases", href: "/results#synthetic" });
  if (stats) out.push({ k: stats.jobs === 1 ? "run stored on this server" : "runs stored on this server", v: fmtInt(stats.jobs), href: "/jobs" });
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
      <ul className="no-scrollbar flex min-w-0 items-stretch overflow-x-auto" aria-label="Numbers from this server">
        {items.length === 0 ? (
          <li className="px-3 py-2 text-subtle">reading /stats and /bench…</li>
        ) : (
          items.map((it, i) => (
            <li key={it.k} className={i > 1 ? "hidden border-l border-border sm:flex" : i > 0 ? "flex border-l border-border" : "flex"}>
              <a href={it.href} className="press flex items-baseline gap-1.5 px-3 py-2 whitespace-nowrap hover:bg-surface-2">
                <CountUp text={it.v} className="font-semibold text-fg" />
                <span className="text-muted">{it.k}</span>
                {it.note ? <span className="text-subtle">({it.note})</span> : null}
              </a>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
