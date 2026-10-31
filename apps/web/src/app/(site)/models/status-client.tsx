"use client";

import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { AlertTriangle, Check, KeyRound, Lock, MapPin, Unlock, X } from "lucide-react";
import { useAdmin } from "@/components/admin-access";
import { PipelineDiagram } from "@/components/models/pipeline-diagram";
import { Container, PageHeader, Section } from "@/components/layout/page";
import { Badge } from "@/components/ui/badge";
import { ErrorState } from "@/components/ui/error-state";
import { ModeBadge } from "@/components/ui/provenance";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { ProviderStatus, Status } from "@/lib/api-types";
import { fmtInt, fmtMs, fmtUsd, titleCase } from "@/lib/format";
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

function Warnings({ items }: { items: string[] }) {
  const [all, setAll] = React.useState(false);
  const shown = all ? items : items.slice(0, 3);
  return (
    <div role="note" aria-label="Provider warnings" className="space-y-1.5 rounded-lg border border-warn-border bg-warn-soft p-4">
      {shown.map((w) => (
        <p key={w} className="flex items-start gap-2 text-[13px]">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden /> {w}
        </p>
      ))}
      {items.length > 3 ? (
        <button type="button" onClick={() => setAll((v) => !v)} aria-expanded={all} className="pl-6 text-[12.5px] font-medium text-fg underline underline-offset-2">
          {all ? "Show fewer" : `Show all ${items.length} warnings`}
        </button>
      ) : null}
    </div>
  );
}

const MODE_WORD: Record<string, string> = { live: "live", replay: "recorded", mock: "mock" };

/** How a stage ran, in one plain word; live gets the accent, recorded and mock the hatched label. */
function ModeWord({ mode }: { mode: string }) {
  return (
    <Badge tone={mode === "live" ? "accent" : "mock"}>{MODE_WORD[mode] ?? mode}</Badge>
  );
}

/**
 * Public view: one row per stage and model. Rows with calls come from the server's model_call log (how those calls ran);
 * a stage with no logged calls shows the model and mode it would use now.
 */
function StageTable({ s }: { s: Status }) {
  const rows = s.providers.flatMap((p) => {
    const calls = s.model_calls.filter((m) => m.stage === p.stage);
    if (!calls.length) return [{ key: `${p.stage}-${p.role}`, role: p.role, stage: p.stage, model: p.model, open: p.open_weights, mode: p.mode, calls: 0, usd: null as number | null }];
    return calls.map((m) => ({ key: `${p.stage}-${p.role}-${m.model}-${m.mode}`, role: p.role, stage: p.stage, model: m.model, open: m.open_weights, mode: m.mode, calls: m.calls, usd: m.usd as number | null }));
  });
  return (
    <div tabIndex={0} role="region" aria-label="Models by stage" className="scrollbar-thin overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full min-w-[560px] text-[13px]">
        <thead className="bg-surface-2 text-left text-[11px] text-subtle">
          <tr>
            {["Stage", "Model", "Mode", "Calls", "Cost"].map((h, i) => (
              <th key={h} scope="col" className={cn("px-3 py-2 font-medium whitespace-nowrap", i >= 3 && "text-right")}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-t border-border">
              <th scope="row" className="px-3 py-2 text-left font-normal whitespace-nowrap">
                {r.role} <span className="text-subtle">· {titleCase(r.stage)}</span>
              </th>
              <td className="px-3 py-2 font-mono text-[12px]">
                {r.model}
                {r.open ? <Badge tone="accent" className="ml-1.5 font-sans">open weights</Badge> : null}
              </td>
              <td className="px-3 py-2">
                <ModeWord mode={r.mode} />
              </td>
              <td className="px-3 py-2 text-right font-mono tnum">{r.calls ? fmtInt(r.calls) : "—"}</td>
              <td className="px-3 py-2 text-right font-mono tnum">{r.usd != null ? fmtUsd(r.usd) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function StatusClient() {
  const q = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 15_000 });
  const h = useQuery({ queryKey: ["health"], queryFn: api.health, retry: false });
  const s = q.data;
  // env-var diagnostics and provider warnings are for whoever runs this server, not for visitors
  const { hasToken } = useAdmin();
  return (
    <>
      <PageHeader
        eyebrow="Models"
        title="Which model ran where"
        description="Every model call goes through one provider layer. When a key is missing that stage falls back to a deterministic mock — shown here and labelled on every result."
        actions={
          s ? (
            <div className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-[13px]">
              <span className="text-muted">Right now</span>
              <ModeWord mode={s.mode} />
              {h.data ? <span className="font-mono text-[12px] text-subtle">v{h.data.version}</span> : null}
            </div>
          ) : null
        }
      />
      <Container className="space-y-12 py-8">
        {q.isError ? (
          <ErrorState error={q.error} what="provider status" onRetry={() => void q.refetch()} />
        ) : !s ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-44" />
            ))}
          </div>
        ) : (
          <>
            <Section
              title="From photo to part"
              description="The fix pipeline, step by step. Each model step shows the model that runs it on this server right now and how it runs; dashed steps are plain code or a person."
            >
              <PipelineDiagram providers={s.providers} />
            </Section>
            <Section
              title="Providers by stage"
              description="Each step of the pipeline, the model behind it, and the calls logged on this server. Mode is how those calls ran; a step with no calls shows how it would run now (recorded = answers played back from saved runs)."
            >
              <StageTable s={s} />
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
            {s.open_weights ? (
              <Section title="Open weights" description="Which stages actually ran live on open-weights models on this server.">
                <div className="flex flex-wrap items-center gap-2 text-[13px]">
                  <Badge tone={s.open_weights.open_weights_only ? "ok" : "neutral"}>
                    {s.open_weights.open_weights_only ? "open-weights-only mode" : "mixed providers"}
                  </Badge>
                  <span className="text-muted">
                    <span className="font-mono text-fg tnum">{fmtInt(s.open_weights.calls_on_open_weights)}</span> calls on open weights
                  </span>
                  <span className="text-muted">
                    · live stages:{" "}
                    {s.open_weights.stages_live_on_open_weights.length ? (
                      <span className="font-mono text-fg">{s.open_weights.stages_live_on_open_weights.join(", ")}</span>
                    ) : (
                      "none yet"
                    )}
                  </span>
                </div>
              </Section>
            ) : null}
            {hasToken ? (
              <>
                <Section title="Server diagnostics" description="Admin only: keys, warnings and per-provider notes for whoever runs this server.">
                  {s.warnings.length ? <Warnings items={s.warnings} /> : null}
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {s.providers.map((p) => (
                      <ProviderCard key={`${p.stage}-${p.role}`} p={p} />
                    ))}
                  </div>
                </Section>
                <Section title="Model calls" description="Every model_call event from every non-replay job, grouped by stage and model.">
                  {s.model_calls.length ? (
                    <div tabIndex={0} role="region" aria-label="Model calls" className="scrollbar-thin overflow-x-auto rounded-lg border border-border bg-surface">
                      <table className="w-full min-w-[720px] text-[12.5px]">
                        <thead className="bg-surface-2 text-left text-[11px] text-subtle">
                          <tr>
                            {["Stage", "Model", "Mode", "Calls", "Failed", "Tokens in / out", "Mean latency", "Cost"].map((h, i) => (
                              <th key={h} scope="col" className={cn("px-3 py-2 font-medium whitespace-nowrap", i >= 3 && "text-right")}>
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="font-mono tnum">
                          {s.model_calls.map((m) => (
                            <tr key={`${m.stage}-${m.provider}-${m.model}`} className="border-t border-border">
                              <th scope="row" className="px-3 py-2 text-left font-sans font-normal whitespace-nowrap">{titleCase(m.stage)}</th>
                              <td className="px-3 py-2">
                                {m.model}
                                {m.open_weights ? <Badge tone="accent" className="ml-1.5 font-sans">open</Badge> : null}
                              </td>
                              <td className="px-3 py-2">
                                <ModeBadge mode={m.mode} />
                              </td>
                              <td className="px-3 py-2 text-right">{fmtInt(m.calls)}</td>
                              <td className={cn("px-3 py-2 text-right", m.failed > 0 && "text-bad")}>{fmtInt(m.failed)}</td>
                              <td className="px-3 py-2 text-right">
                                {fmtInt(m.tokens_in)} / {fmtInt(m.tokens_out)}
                              </td>
                              <td className="px-3 py-2 text-right">{fmtMs(m.ms_mean)}</td>
                              <td className="px-3 py-2 text-right">{fmtUsd(m.usd)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="text-[13px] text-muted">No model calls recorded yet.</p>
                  )}
                </Section>
              </>
            ) : null}
          </>
        )}
      </Container>
    </>
  );
}
