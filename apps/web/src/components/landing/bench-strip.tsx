"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, FlaskConical, Hourglass } from "lucide-react";
import Link from "next/link";
import { api, ApiError } from "@/lib/api";
import type { BenchTable } from "@/lib/api-types";
import { BENCH_TABLES, benchHeadline } from "@/lib/bench";
import { Badge } from "../ui/badge";
import { Skeleton } from "../ui/skeleton";

/** Honest bench strip: one card per ground-truth source, each with N and its source; "pending" when not generated yet. */
export function BenchStrip() {
  const q = useQuery({ queryKey: ["bench"], queryFn: api.bench, retry: false });
  const missing = q.isError && (q.error instanceof ApiError ? q.error.status === 404 : true);
  return (
    <div className="grid gap-3 md:grid-cols-3">
      {BENCH_TABLES.map((t) => {
        const table: BenchTable | null | undefined = q.data?.tables[t.key];
        const head = table ? benchHeadline(table) : null;
        return (
          <Link
            key={t.key}
            href={`/bench#${t.key}`}
            className="group flex flex-col gap-3 rounded-xl border border-border bg-surface p-5 transition-colors hover:border-border-strong"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-[13px] font-semibold text-fg">{t.title}</span>
              <ArrowUpRight className="size-4 text-subtle transition-colors group-hover:text-fg" aria-hidden />
            </div>
            <p className="text-[12px] leading-5 text-muted">{t.blurb}</p>
            <div className="mt-auto">
              {q.isPending ? (
                <Skeleton className="h-8 w-32" />
              ) : head ? (
                <div className="space-y-1.5">
                  <div className="font-mono text-[22px] leading-none font-medium tnum">{head.value}</div>
                  <div className="flex flex-wrap gap-1.5">
                    <Badge tone="neutral" className="font-mono tnum">N = {head.n ?? "—"}</Badge>
                    <Badge tone="outline">
                      <FlaskConical aria-hidden /> {head.gt}
                    </Badge>
                  </div>
                </div>
              ) : (
                <Badge tone="mock">
                  <Hourglass aria-hidden /> {missing || !q.data ? "bench not generated yet" : `pending ${t.pendingLabel}`}
                </Badge>
              )}
            </div>
          </Link>
        );
      })}
    </div>
  );
}
