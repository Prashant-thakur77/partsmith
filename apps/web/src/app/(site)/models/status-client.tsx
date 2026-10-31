"use client";

import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { AlertTriangle, Check, KeyRound, Lock, MapPin, Unlock, X } from "lucide-react";
import { useAdmin } from "@/components/admin-access";
import { PipelineDiagram } from "@/components/models/pipeline-diagram";
import { ModeWord, StageModelsTable } from "@/components/models/stage-models-table";
import { Container, PageHeader, Section } from "@/components/layout/page";
import { Badge } from "@/components/ui/badge";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { ProviderStatus } from "@/lib/api-types";
import { fmtInt, fmtMs, fmtUsd, titleCase } from "@/lib/format";
import { MODE_WORD } from "@/lib/stage-models";
import { cn } from "@/lib/utils";

function ProviderCard({ p }: { p: ProviderStatus }) {
  return (
    <div className={cn("flex flex-col gap-3 rounded-lg border bg-surface p-4", p.mode === "live" ? "border-border" : "border-dashed border-border-strong")}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-subtle">{titleCase(p.stage)}</div>
          <div className="text-[14px] font-semibold">{p.role}</div>
        </div>
        <ModeWord mode={p.mode} />
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

const MODE_MEANS: [string, string][] = [
  ["live", "a real model call"],
  ["replay", "a saved model answer played back"],
  ["mock", "a deterministic stand-in, not model output"],
];

/** The one legend for the mode words used everywhere on this page. */
function ModeLegend() {
  return (
    <p className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12px] text-muted" data-testid="mode-legend">
      {MODE_MEANS.map(([m, means]) => (
        <span key={m} className="inline-flex items-center gap-1.5">
          <ModeWord mode={m} /> {means}
        </span>
      ))}
    </p>
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
              <span className="text-muted">Runs now</span>
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
              description="Each step of the pipeline: the model it is set up to use and how it runs now, beside the models actually seen in its logged calls and how each of those calls ran. Calls made on this server and calls inside the recorded runs it serves are listed apart; only the first are spend."
            >
              <ModeLegend />
              <StageModelsTable s={s} />
            </Section>
            <Section title="Jobs and cost" description="Totals from the jobs made on this server (the recorded runs it plays back are left out, so /jobs lists more).">
              <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border md:grid-cols-4">
                {[
                  { k: "Jobs run here", v: fmtInt(s.jobs.total), sub: "recorded runs not counted" },
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
                  <span className="text-muted" data-testid="open-weights-line">
                    <span className="font-mono text-fg tnum">{fmtInt(s.open_weights.calls_on_open_weights)}</span> model call
                    {s.open_weights.calls_on_open_weights === 1 ? "" : "s"} in this server&apos;s job log ran live on open-weight models.{" "}
                    {s.open_weights.stages_live_on_open_weights.length ? (
                      <>
                        Set to use them live right now: <span className="font-mono text-fg">{s.open_weights.stages_live_on_open_weights.join(", ")}</span>.
                      </>
                    ) : (
                      <>No stage is set to use them live right now{s.mode !== "live" ? ` (this server answers in ${MODE_WORD[s.mode] ?? s.mode} mode)` : ""}.</>
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
                              <td className="px-3 py-2 font-sans">
                                <ModeWord mode={m.mode} />
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
