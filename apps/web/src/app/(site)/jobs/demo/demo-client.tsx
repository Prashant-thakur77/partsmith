"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, FlaskConical, History, Play } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { Container, PageHeader, Section } from "@/components/layout/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { ModeBadge, OriginBadge } from "@/components/ui/provenance";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { api } from "@/lib/api";
import { FAMILIES } from "@/lib/families";
import { fmtNum, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

const SAMPLES = FAMILIES.filter((f) => f !== "custom");

export function DemoClient() {
  const router = useRouter();
  const [sample, setSample] = React.useState<string>(SAMPLES[0] ?? "clip");
  const run = useMutation({
    mutationFn: (s: string) => api.createDemoJob(s),
    onSuccess: (job) => router.push(`/jobs/${encodeURIComponent(job.id)}`),
  });
  const replays = useQuery({ queryKey: ["replays"], queryFn: api.replays });

  return (
    <>
      <PageHeader
        eyebrow="Try it without a part"
        title="Run a synthetic sample"
        description="A bundled, rendered photo with exact ground truth goes through the real pipeline — capture gate, measuring, CAD, verifier. Everything it produces is labelled synthetic."
      />
      <Container className="space-y-14 py-10">
        <Section title="Pick a sample" description="Each sample is a rendered part of one family on the screen mat.">
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Sample">
            {SAMPLES.map((s) => (
              <button
                key={s}
                type="button"
                role="radio"
                aria-checked={sample === s}
                onClick={() => setSample(s)}
                className={cn(
                  "h-8 rounded-full border px-3 text-[13px] transition-colors",
                  sample === s ? "border-fg bg-fg text-bg" : "border-border bg-surface text-muted hover:border-border-strong hover:text-fg",
                )}
              >
                {titleCase(s)}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" size="lg" onClick={() => run.mutate(sample)} disabled={run.isPending}>
              {run.isPending ? <Spinner className="text-accent-fg" label="Starting" /> : <Play aria-hidden />}
              Run the {titleCase(sample).toLowerCase()} sample
            </Button>
            <Badge tone="mock">
              <FlaskConical aria-hidden /> synthetic input
            </Badge>
          </div>
          {run.isError ? <ErrorState error={run.error} compact what="the sample job" /> : null}
        </Section>

        <Section title="Or watch a recorded run" description="Replays play back a stored run log event by event. Nothing is recomputed, and they are labelled replay.">
          {replays.isPending ? (
            <div className="grid gap-3 md:grid-cols-2">
              {[0, 1].map((i) => (
                <Skeleton key={i} className="h-24" />
              ))}
            </div>
          ) : replays.isError ? (
            <ErrorState error={replays.error} compact what="replays" onRetry={() => void replays.refetch()} />
          ) : replays.data.length === 0 ? (
            <EmptyState icon={History} title="No stored runs yet" compact>
              Runs are recorded automatically; the first finished job becomes replayable.
            </EmptyState>
          ) : (
            <ul className="grid gap-3 md:grid-cols-2">
              {replays.data.map((r) => (
                <li key={r.id}>
                  <Link
                    href={`/jobs/${encodeURIComponent(r.id)}`}
                    className="group flex items-center justify-between gap-4 rounded-lg border border-border bg-surface p-4 hover:border-border-strong"
                  >
                    <div className="min-w-0 space-y-2">
                      <div className="truncate text-[14px] font-medium">{r.title}</div>
                      <div className="flex flex-wrap gap-1.5">
                        <OriginBadge origin={r.origin} />
                        <ModeBadge mode={r.provider_mode} />
                        <Badge tone={r.verified ? "ok" : "warn"}>{r.verified ? "verified" : "not verified"}</Badge>
                        <Badge tone="neutral" className="font-mono tnum">
                          {r.iterations} iter · {r.max_error_mm != null ? `${fmtNum(r.max_error_mm)} mm` : "—"}
                        </Badge>
                      </div>
                    </div>
                    <ArrowRight className="size-4 shrink-0 text-subtle group-hover:text-fg" aria-hidden />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </Container>
    </>
  );
}
