"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Check, KeyRound, Lock, MapPin, Unlock, X } from "lucide-react";
import { Container, PageHeader, Section } from "@/components/layout/page";
import { Badge } from "@/components/ui/badge";
import { ErrorState } from "@/components/ui/error-state";
import { ModeBadge } from "@/components/ui/provenance";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { ProviderStatus } from "@/lib/api-types";
import { fmtInt, fmtUsd, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

function ProviderCard({ p }: { p: ProviderStatus }) {
  return (
    <div className={cn("flex flex-col gap-3 rounded-lg border bg-surface p-4", p.mode === "live" ? "border-border" : "border-dashed border-border-strong")}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-subtle">{titleCase(p.stage)}</div>
          <div className="text-[14px] font-semibold">{p.role}</div>
        </div>
        <ModeBadge mode={p.mode} />
      </div>
      <div className="min-w-0 space-y-1">
        <div className="truncate font-mono text-[12.5px] text-fg" title={p.model}>
          {p.model}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-muted">
          <span className="inline-flex items-center gap-1">
            <MapPin className="size-3.5" aria-hidden /> {p.provider} · {p.where}
          </span>
        </div>
      </div>
      <div className="mt-auto flex flex-wrap gap-1.5">
        {p.open_weights ? (
          <Badge tone="accent">
            <Unlock aria-hidden /> open weights
          </Badge>
        ) : (
          <Badge tone="neutral">
            <Lock aria-hidden /> hosted API
          </Badge>
        )}
        {p.key_env ? (
          <Badge tone={p.key_present ? "ok" : "warn"} className="font-mono">
            <KeyRound aria-hidden />
            {p.key_env} {p.key_present ? <Check aria-label="present" /> : <X aria-label="missing" />}
          </Badge>
        ) : null}
      </div>
      {p.note ? <p className="border-t border-border pt-2 text-[12px] leading-5 text-muted">{p.note}</p> : null}
    </div>
  );
}

export function StatusClient() {
  const q = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 15_000 });
  const h = useQuery({ queryKey: ["health"], queryFn: api.health, retry: false });
  const s = q.data;
  return (
    <>
      <PageHeader
        eyebrow="Status"
        title="Which model ran where"
        description="Every model call goes through one provider layer. When a key is missing that stage falls back to a deterministic mock — shown here and labelled on every result."
        actions={
          s ? (
            <div className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-[13px]">
              <span className="text-muted">Overall mode</span>
              <ModeBadge mode={s.mode} />
              {h.data ? <span className="font-mono text-[12px] text-subtle">v{h.data.version}</span> : null}
            </div>
          ) : null
        }
      />
      <Container className="space-y-12 py-8">
        {q.isError ? (
          <ErrorState error={q.error} what="provider status" onRetry={() => void q.refetch()} />
        ) : !s ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-44" />
            ))}
          </div>
        ) : (
          <>
            {s.warnings.length ? (
              <div role="alert" className="space-y-1.5 rounded-lg border border-warn-border bg-warn-soft p-4">
                {s.warnings.map((w) => (
                  <p key={w} className="flex items-start gap-2 text-[13px]">
                    <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden /> {w}
                  </p>
                ))}
              </div>
            ) : null}
            <Section title="Providers by stage">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {s.providers.map((p) => (
                  <ProviderCard key={`${p.stage}-${p.role}`} p={p} />
                ))}
              </div>
            </Section>
            <Section title="Jobs and cost" description="Totals from the job log on this instance.">
              <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border md:grid-cols-4">
                {[
                  { k: "Jobs run", v: fmtInt(s.jobs.total) },
                  { k: "Verified", v: fmtInt(s.jobs.verified) },
                  { k: "Model spend", v: fmtUsd(s.cost.usd_total) },
                  { k: "Mean per job", v: s.cost.usd_per_job_mean != null ? fmtUsd(s.cost.usd_per_job_mean) : "—", sub: `over ${fmtInt(s.cost.n_jobs)} jobs` },
                ].map((it) => (
                  <div key={it.k} className="space-y-1.5 bg-surface p-5">
                    <dt className="text-[12px] text-muted">{it.k}</dt>
                    <dd className="font-mono text-[26px] leading-none font-medium tnum">{it.v}</dd>
                    {it.sub ? <dd className="text-[12px] text-subtle">{it.sub}</dd> : null}
                  </div>
                ))}
              </dl>
            </Section>
          </>
        )}
      </Container>
    </>
  );
}
