"use client";

/**
 * Three big numbers, each with where it came from: the synthetic and reference-object bench headlines (as eval/ wrote
 * them, each with how many of the same cases passed verification) and the lying-model attacks code blocked. A table
 * that has not run says so instead of showing a number.
 */
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { BenchReport } from "@/lib/api-types";
import { benchHeadline, benchVerified, gtLabel } from "@/lib/bench";
import { cn } from "@/lib/utils";
import { CountUp } from "../ui/count-up";
import { Skeleton } from "../ui/skeleton";

type Cell = { key: string; label: string; value: string | null; source: string; href: string; pending?: string; passed?: string };

export function proofCells(b: BenchReport | undefined): Cell[] {
  const cell = (key: "synthetic" | "reference_objects", label: string, noun: string): Cell => {
    const t = b?.tables[key];
    const head = t ? benchHeadline(t) : null;
    const ver = benchVerified(t);
    return {
      key,
      label,
      value: head && /median/.test(head.gt) ? head.value : null,
      source: t && head ? `bench · ${t.n} ${noun} · ground truth: ${gtLabel(t.ground_truth)}` : `bench · ${noun}`,
      href: `/results#${key}`,
      pending: t?.status === "pending" || !head ? "not run yet" : undefined,
      passed: ver ? `${ver.passed} of ${ver.n} passed verification (all checks within limits)` : undefined,
    };
  };
  const by = b?.evidence?.bypass;
  return [
    cell("synthetic", "median size error, rendered test photos", "synthetic photos"),
    cell("reference_objects", "median size error, standard objects", "reference objects"),
    {
      key: "bypass",
      label: "lying-model attacks blocked by code",
      value: by ? `${by.blocked}/${by.attempts}` : null,
      source: by ? `bench evidence · ${by.suite}` : "bench evidence · lying-model suite",
      href: "/judges",
      pending: by ? undefined : "not run yet",
    },
  ];
}

export function ProofStrip({ bench: initial }: { bench?: BenchReport | null }) {
  const q = useQuery({ queryKey: ["bench"], queryFn: api.bench, initialData: initial ?? undefined, initialDataUpdatedAt: 0, retry: false, staleTime: 300_000 });
  const cells = proofCells(q.data).map((c) => (q.isError ? { ...c, pending: "API offline" } : c));
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-1 overflow-hidden rounded-xl border border-border bg-surface md:grid-cols-3 md:divide-x md:divide-border">
        {cells.map((c, i) => (
          <div key={c.key} data-reveal style={{ "--reveal-i": i } as React.CSSProperties} className={cn("group relative flex flex-col gap-3 p-6 sm:p-7", i > 0 && "border-t border-border md:border-t-0")}>
            <dt className="order-2 text-[14px] leading-5 font-medium text-fg">
              {c.label}
              {c.passed && c.value ? <span className="mt-1 block text-[13px] font-normal text-muted">{c.passed}</span> : null}
            </dt>
            <dd className="order-1 font-mono text-[44px] leading-none font-medium tracking-[-0.04em] text-fg sm:text-[56px]">
              {q.isPending ? <Skeleton className="h-12 w-40" /> : c.value ? <CountUp text={c.value} unitClassName="ml-1 text-[0.42em] tracking-normal text-muted" /> : <span className="text-[20px] tracking-normal text-subtle">{c.pending ?? "—"}</span>}
            </dd>
            <dd className="order-3 mt-auto flex items-start justify-between gap-3 border-t border-dashed border-border pt-3 font-mono text-[11px] leading-4 text-subtle">
              <span>{c.source}</span>
              <Link href={c.href} className="press -m-1 shrink-0 rounded p-1 text-muted hover:text-fg" aria-label={`Source: ${c.label}`}>
                <ArrowUpRight className="size-3.5" aria-hidden />
              </Link>
            </dd>
          </div>
        ))}
      </dl>
      {q.data?.label ? <p className="font-mono text-[11px] text-subtle">Report label: {q.data.label}{q.data.generated_at ? ` · generated ${String(q.data.generated_at).slice(0, 10)}` : ""}</p> : null}
    </div>
  );
}
