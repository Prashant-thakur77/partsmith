"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import * as React from "react";
import { ChevronRight, FlaskConical, GitCommit, Hourglass, ImageOff } from "lucide-react";
import { Container, PageHeader, Section } from "@/components/layout/page";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { ModeBadge } from "@/components/ui/provenance";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError, artifactUrl } from "@/lib/api";
import type { BenchTable } from "@/lib/api-types";
import { BENCH_TABLES, EXTRA_TITLES, benchCell, benchHeadline, benchSentence, benchVerified, caseLabel, cellText, columnLabel, configLabel, gtLabel, KEY_COLUMNS, plainBench, splitCaseTitle } from "@/lib/bench";
import { PRODUCT, productApi } from "@/lib/api-product";
import { useCapabilities } from "@/lib/capabilities";
import { titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Template name → title ("hook" → "Wall hook") for naming bench cases, when this server lists templates. */
function useTemplateTitles(): Record<string, string> {
  const caps = useCapabilities();
  const q = useQuery({ queryKey: ["templates"], queryFn: productApi.templates, enabled: caps.has("get", PRODUCT.templates), staleTime: 300_000, retry: false });
  return React.useMemo(() => Object.fromEntries((q.data ?? []).map((t) => [t.name, t.title])), [q.data]);
}

function TableView({ t, only, label }: { t: BenchTable; only?: readonly string[]; label?: string }) {
  const titles = useTemplateTitles();
  const rows = t.rows ?? [];
  const all = t.columns ?? (rows[0] ? Object.keys(rows[0]) : []);
  const cols = only ? all.filter((c) => only.includes(c)) : all;
  if (!rows.length) return <p className="text-[13px] text-muted">The table has no rows.</p>;
  return (
    <div tabIndex={0} role="region" aria-label={label ?? t.title ?? "Bench table"} className="scrollbar-thin overflow-x-auto rounded-lg border border-border bg-surface">
      <table className={cn("w-full text-[12.5px]", only ? "min-w-[480px]" : "min-w-[560px]")}>
        <thead className="bg-surface-2 text-left text-[11px] text-subtle">
          <tr>
            {cols.map((c) => (
              <th key={c} scope="col" title={c} className="px-3 py-2 font-medium whitespace-nowrap">
                {columnLabel(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="font-mono tnum">
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-border">
              {cols.map((c, j) => (
                <td key={c} className={j === 0 ? "px-3 py-2 font-sans whitespace-nowrap" : "px-3 py-2 whitespace-nowrap"}>
                  {c === "config" && typeof r[c] === "string" ? (
                    <span title={`${r[c]}${typeof r.description === "string" ? `: ${r.description}` : ""}`}>{configLabel(r[c])}</span>
                  ) : c === "case" && typeof r[c] === "string" ? (
                    <span className="flex flex-col">
                      <span>{caseLabel(r[c], titles)}</span>
                      <span className="font-mono text-[10.5px] text-subtle">{r[c]}</span>
                    </span>
                  ) : (
                    benchCell(c, r[c], r)
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A short table of the key columns, the full eval table behind a disclosure. */
function Tables({ t }: { t: BenchTable }) {
  const all = t.columns ?? (t.rows?.[0] ? Object.keys(t.rows[0]) : []);
  const key = all.filter((c) => KEY_COLUMNS.includes(c));
  const compact = key.length >= 3 && key.length < all.length;
  return (
    <>
      {compact ? <TableView t={t} only={KEY_COLUMNS} label={`${t.title ?? "Bench table"} (key columns)`} /> : null}
      {compact || (t.rows?.length ?? 0) > 3 ? (
        <details className="group rounded-lg">
          <summary className="inline-flex cursor-pointer items-center gap-1 rounded-md text-[13px] font-medium text-accent-text hover:underline">
            <ChevronRight className="size-3.5 transition-transform group-open:rotate-90" aria-hidden /> Show the full table
            <span className="font-normal text-subtle">
              ({all.length} columns, {t.rows?.length ?? 0} rows)
            </span>
          </summary>
          <div className="mt-3">
            <TableView t={t} />
          </div>
        </details>
      ) : (
        <TableView t={t} />
      )}
    </>
  );
}

/** Bench gallery images can be missing on this server (see the report); show a placeholder instead of a broken image. */
function FallbackImg({ src, alt, className }: { src: string; alt: string; className?: string }) {
  const [failed, setFailed] = React.useState(false);
  if (failed)
    return (
      <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-[12px] text-subtle">
        <ImageOff className="size-5" aria-hidden /> overlay image not available
      </div>
    );
  // eslint-disable-next-line @next/next/no-img-element -- bench artifact
  return <img src={src} alt={alt} className={className} onError={() => setFailed(true)} />;
}

export function BenchClient() {
  const q = useQuery({ queryKey: ["bench"], queryFn: api.bench, retry: false });
  const titles = useTemplateTitles();
  const synPassed = benchVerified(q.data?.tables.synthetic);
  const missing = (q.isError && q.error instanceof ApiError && q.error.status === 404) || q.data?.status === "pending";
  const r = q.data;
  const known = new Set<string>(BENCH_TABLES.map((t) => t.key));
  const extra = r ? Object.entries(r.tables).filter(([k]) => !known.has(k)) : [];
  return (
    <>
      <PageHeader
        eyebrow="Results · PartSmith-Bench"
        title="How accurate is it?"
        description="Three ground-truth sources, reported separately and never merged into one number. Every table states N, the confidence interval and what the error is measured against. Tables are generated by the eval scripts — nothing here is typed by hand."
      >
        {r?.label ? (
          <div role="note" className="rounded-md border border-warn-border bg-warn-soft px-3 py-2 text-[13px] text-fg">
            <span className="font-medium">{r.label}</span>
            {r.notes.length ? <span className="block text-[12px] text-muted">{r.notes.join(" · ")}</span> : null}
          </div>
        ) : null}
        {r ? (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {r.mode ? <ModeBadge mode={r.mode} /> : null}
            {r.generated_at ? <Badge tone="neutral">generated {typeof r.generated_at === "number" ? new Date(r.generated_at * 1000).toISOString().slice(0, 16).replace("T", " ") : r.generated_at}</Badge> : null}
            {r.git_sha ? (
              <Badge tone="neutral" className="font-mono">
                <GitCommit aria-hidden /> {r.git_sha.slice(0, 10)}
              </Badge>
            ) : null}
          </div>
        ) : null}
      </PageHeader>
      <Container className="space-y-14 py-10">
        {q.isPending ? (
          <Skeleton className="h-64" />
        ) : q.isError && !missing ? (
          <ErrorState error={q.error} what="the bench report" onRetry={() => void q.refetch()} />
        ) : (
          <>
            {missing ? (
              <EmptyState icon={Hourglass} title="No bench report has been generated yet">
                The tables are built by the eval scripts from stored runs. Until they run there are no accuracy numbers to show — on
                purpose.
              </EmptyState>
            ) : null}
            {[...BENCH_TABLES.map((t) => [t.key, r?.tables[t.key] ?? null, t] as const), ...extra.map(([k, v]) => [k, v, null] as const)].map(([key, table, meta]) => (
              <Section
                key={key}
                id={key}
                title={meta?.title ?? EXTRA_TITLES[key]?.title ?? table?.title ?? titleCase(key)}
                description={meta?.blurb ?? EXTRA_TITLES[key]?.blurb ?? (table?.note ? plainBench(table.note) : undefined)}
              >
                {table && table.status !== "pending" ? (
                  <div className="space-y-3">
                    {table.title ? <p className="text-[13px] font-medium text-fg">{plainBench(table.title)}</p> : null}
                    <div className="flex flex-wrap gap-1.5">
                      <Badge tone="inverse" className="font-mono tnum">N = {table.n}</Badge>
                      <Badge tone="outline" className="whitespace-normal">
                        <FlaskConical aria-hidden /> ground truth: {gtLabel(table.ground_truth, meta?.gt ?? "not stated")}
                      </Badge>
                      <Badge tone={table.ci != null ? "neutral" : "warn"} className="font-mono whitespace-normal">
                        {table.ci != null ? `CI ${cellText(table.ci)}` : "no CI reported"}
                      </Badge>
                    </div>
                    {benchHeadline(table) ? (
                      <div className="font-mono text-[26px] leading-none font-medium tnum">
                        {benchHeadline(table)!.value}{" "}
                        <span className="font-sans text-[13px] font-normal text-muted">{benchHeadline(table)!.gt}</span>
                      </div>
                    ) : null}
                    {benchSentence(key, table) ? <p className="max-w-3xl text-[15px] leading-6 text-fg">{benchSentence(key, table)}</p> : null}
                    {key === "synthetic" && synPassed ? (
                      <p className="max-w-3xl text-[13px] leading-5 text-muted" data-testid="pass-rate-note">
                        This {synPassed.passed}/{synPassed.n} is the strict pass rate on this fixed set of rendered test photos: a case passes only when every check is within 0.5 mm. It is the number on the home page. The verified count on{" "}
                        <Link href="/jobs" className="text-accent-text underline underline-offset-2">
                          Recent jobs
                        </Link>{" "}
                        counts a different set — every job run or recorded on this server — so the two differ.
                      </p>
                    ) : null}
                    <Tables t={table} />
                    {table.note ? (
                      <p className="rounded-md border border-warn-border bg-warn-soft px-3 py-2 text-[12.5px] leading-5 text-fg">{plainBench(table.note)}</p>
                    ) : null}
                  </div>
                ) : (
                  <div className="flex items-center gap-3 rounded-lg border border-dashed border-border-strong bg-surface p-5 text-[13px] text-muted">
                    <Hourglass className="size-4 shrink-0" aria-hidden />
                    <span>
                      Pending {meta?.pendingLabel ?? "table"}. Ground truth when it runs:{" "}
                      <span className="text-fg">{gtLabel(table?.ground_truth, meta?.gt ?? "not stated")}</span>.
                      {table?.note ? <span className="mt-1 block font-mono text-[12px] text-subtle">{plainBench(table.note)}</span> : null}
                    </span>
                  </div>
                )}
              </Section>
            ))}
            <Section id="failures" title="Failure gallery" description="Cases the pipeline got wrong, kept on purpose.">
              {r?.failures.length ? (
                <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {r.failures.map((f, i) => {
                    const img = artifactUrl(f.overlay_url);
                    const { id: caseId, rest } = splitCaseTitle(f.title);
                    const name = caseLabel(caseId, titles);
                    return (
                      <li key={i} className="overflow-hidden rounded-lg border border-border bg-surface">
                        <div className="relative aspect-[4/3] border-b border-border bg-surface-2">
                          {img ? (
                            <FallbackImg src={img} alt={`Failure: ${name}`} className="absolute inset-0 size-full object-contain" />
                          ) : (
                            <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 px-4 text-center text-[12px] text-subtle">
                              <ImageOff className="size-5" aria-hidden />
                              No overlay image was saved for this run.
                            </div>
                          )}
                        </div>
                        <div className="space-y-1 p-3 text-[12.5px]">
                          <div className="font-medium">{name}</div>
                          <p className="text-muted">{f.reason}</p>
                          {name !== caseId || rest ? (
                            <p className="font-mono text-[10.5px] text-subtle [overflow-wrap:anywhere]">
                              {[name !== caseId ? caseId : null, rest ? plainBench(rest) : null].filter(Boolean).join(" · ")}
                            </p>
                          ) : null}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <EmptyState compact icon={ImageOff} title={r ? "No failures recorded in this report" : "Pending"} />
              )}
            </Section>
          </>
        )}
      </Container>
    </>
  );
}
