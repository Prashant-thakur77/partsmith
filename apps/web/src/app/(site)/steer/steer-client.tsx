"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CornerUpLeft, Factory, Send, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { Container, PageHeader, Section } from "@/components/layout/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Kbd } from "@/components/ui/kbd";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { toast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import type { SteerLane, SteerQueueItem } from "@/lib/api-types";
import { fmtNum, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

function laneTone(l: SteerLane): "ok" | "warn" | "bad" | "accent" | "neutral" {
  if (l.verified) return "ok";
  if (/fail|reject/.test(l.status)) return "bad";
  if (/best|send/.test(l.status)) return "warn";
  if (/run|build|verify|queued/.test(l.status)) return "accent";
  return "neutral";
}

function ApprovalQueue({ runId, queue }: { runId: string; queue: SteerQueueItem[] }) {
  const qc = useQueryClient();
  const [sel, setSel] = React.useState(0);
  const [note, setNote] = React.useState("");
  const review = useMutation({
    mutationFn: (v: { slug: string; action: "approve" | "send_back" | "reject" }) => api.steerReview(runId, { ...v, note }),
    onSuccess: (_d, v) => {
      toast(v.action === "approve" ? "Approved" : v.action === "reject" ? "Rejected" : "Sent back", { description: v.slug, tone: v.action === "approve" ? "ok" : "info" });
      setNote("");
      void qc.invalidateQueries({ queryKey: ["steer", runId] });
    },
    onError: () => toast("Review failed", { tone: "bad" }),
  });
  const cur = queue[Math.min(sel, queue.length - 1)];

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("input, textarea, select, [contenteditable]") || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "j" || e.key === "ArrowDown") setSel((i) => Math.min(queue.length - 1, i + 1));
      else if (e.key === "k" || e.key === "ArrowUp") setSel((i) => Math.max(0, i - 1));
      else if (cur && !review.isPending && (e.key === "a" || e.key === "s" || e.key === "r")) {
        e.preventDefault();
        review.mutate({ slug: cur.slug, action: e.key === "a" ? "approve" : e.key === "s" ? "send_back" : "reject" });
      } else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [queue.length, cur, review]);

  if (!queue.length) return <EmptyState compact icon={Check} title="Nothing waiting for review" />;
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface" role="listbox" aria-label="Approval queue" aria-activedescendant={cur ? `q-${cur.slug}` : undefined}>
        {queue.map((q, i) => (
          <li
            key={q.slug}
            id={`q-${q.slug}`}
            role="option"
            aria-selected={i === sel}
            onClick={() => setSel(i)}
            className={cn("flex cursor-pointer items-center gap-3 px-4 py-3", i === sel ? "bg-accent-soft" : "hover:bg-surface-2")}
          >
            <span className={cn("h-8 w-0.5 rounded-full", i === sel ? "bg-accent" : "bg-transparent")} aria-hidden />
            <div className="min-w-0 flex-1">
              <div className="truncate text-[14px] font-medium">{q.title ?? q.slug}</div>
              <div className="truncate font-mono text-[12px] text-subtle">{q.slug}</div>
            </div>
            {q.judge ? <span className="hidden max-w-[40%] truncate text-[12px] text-muted md:block">judge: {q.judge}</span> : null}
            <Badge tone={q.verified ? "ok" : "warn"} className="font-mono tnum">
              {q.verified ? "verified" : "not verified"}
              {q.max_error_mm != null ? ` · ${fmtNum(q.max_error_mm)} mm` : ""}
            </Badge>
          </li>
        ))}
      </ul>
      <div className="space-y-3 rounded-lg border border-border bg-surface p-4 lg:sticky lg:top-24 lg:self-start">
        <div className="text-[13px] font-semibold">Review {cur?.title ?? cur?.slug}</div>
        <div className="space-y-1.5">
          <Label htmlFor="note">Note (optional)</Label>
          <Input id="note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. hook too thin for PLA" />
        </div>
        <div className="grid grid-cols-3 gap-2">
          <Button size="sm" variant="solid" disabled={!cur || review.isPending} onClick={() => cur && review.mutate({ slug: cur.slug, action: "approve" })}>
            <Check aria-hidden /> Approve
          </Button>
          <Button size="sm" variant="outline" disabled={!cur || review.isPending} onClick={() => cur && review.mutate({ slug: cur.slug, action: "send_back" })}>
            <CornerUpLeft aria-hidden /> Send back
          </Button>
          <Button size="sm" variant="outline" disabled={!cur || review.isPending} onClick={() => cur && review.mutate({ slug: cur.slug, action: "reject" })}>
            <X aria-hidden /> Reject
          </Button>
        </div>
        <p className="flex flex-wrap items-center gap-1 text-[12px] text-muted">
          <Kbd>a</Kbd> approve <Kbd>s</Kbd> send back <Kbd>r</Kbd> reject <Kbd>j</Kbd>/<Kbd>k</Kbd> move
        </p>
        {cur?.job_id ? (
          <Link href={`/jobs/${encodeURIComponent(cur.job_id)}`} className="text-[12px] text-accent-text hover:underline">
            Open the build trace
          </Link>
        ) : null}
      </div>
    </div>
  );
}

export function SteerClient() {
  const router = useRouter();
  const pathname = usePathname();
  const runId = useSearchParams().get("id");
  const [brief, setBrief] = React.useState("");
  const [count, setCount] = React.useState(8);
  const start = useMutation({
    mutationFn: () => api.steer(brief.trim(), count),
    onSuccess: (r) => router.push(`${pathname}?id=${encodeURIComponent(r.id)}`),
  });
  const run = useQuery({
    queryKey: ["steer", runId],
    queryFn: () => api.steerRun(runId!),
    enabled: !!runId,
    refetchInterval: (q) => (q.state.data?.lanes.every((l) => /verified|fail|reject|best|done|approved/.test(l.status)) ? false : 2500),
  });
  const r = run.data;
  const done = r ? r.lanes.filter((l) => l.verified).length : 0;

  return (
    <>
      <PageHeader
        eyebrow="Steer"
        title="A family of parts from one line"
        description="Write a brief. A planner model proposes the family, builder agents make each part, the verifier measures every one, and you approve what gets published."
      />
      <Container className="space-y-12 py-8">
        <form
          className="space-y-3 rounded-xl border border-border bg-surface p-5"
          onSubmit={(e) => {
            e.preventDefault();
            if (brief.trim()) start.mutate();
          }}
        >
          <Label htmlFor="brief">Brief</Label>
          <Textarea id="brief" value={brief} onChange={(e) => setBrief(e.target.value)} rows={2} placeholder="Cupboard hardware kit, 4 mm grid: latches, hinge pins, shelf supports" />
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="flex items-center gap-2">
              <Label htmlFor="count">Parts</Label>
              <Input id="count" type="number" min={1} max={30} value={count} onChange={(e) => setCount(Math.max(1, Math.min(30, Number(e.target.value) || 1)))} className="w-20 font-mono tnum" />
            </div>
            <Button type="submit" variant="primary" disabled={!brief.trim() || start.isPending}>
              {start.isPending ? <Spinner className="text-accent-fg" label="Planning" /> : <Send aria-hidden />} Plan and build
            </Button>
          </div>
          {start.isError ? <ErrorState error={start.error} compact what="the steer run" /> : null}
        </form>

        {!runId ? (
          <EmptyState icon={Factory} title="No run selected">
            Start a run above. Each part goes through the same verifier as a photo fix; nothing is published without approval.
          </EmptyState>
        ) : run.isError ? (
          <ErrorState error={run.error} what="this run" onRetry={() => void run.refetch()} />
        ) : !r ? (
          <Skeleton className="h-64" />
        ) : (
          <>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div>
                <div className="text-[12px] text-muted">Run <span className="font-mono">{r.id}</span></div>
                <div className="text-[18px] font-semibold">{r.brief}</div>
              </div>
              <div className="font-mono text-[14px] tnum">
                {done}/{r.plan.length || r.lanes.length} verified
              </div>
            </div>
            <Section title="Plan">
              <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {r.plan.map((p) => (
                  <li key={p.slug} className="space-y-1 rounded-md border border-border bg-surface p-3">
                    <div className="text-[13px] font-medium">{p.title}</div>
                    <div className="flex items-center gap-1.5 text-[12px] text-muted">
                      <Badge tone="neutral">{titleCase(p.family)}</Badge>
                      <span className="truncate font-mono">{Object.entries(p.params).slice(0, 3).map(([k, v]) => `${k}=${String(v)}`).join(" ")}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </Section>
            <Section title="Build lanes">
              <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface">
                {r.lanes.map((l) => (
                  <li key={l.slug} className="flex items-center gap-3 px-4 py-2.5 text-[13px]">
                    <span className="min-w-0 flex-1 truncate font-mono">{l.slug}</span>
                    {l.max_error_mm != null ? <span className="font-mono text-[12px] text-muted tnum">{fmtNum(l.max_error_mm)} mm</span> : null}
                    <Badge tone={laneTone(l)}>{l.status.replace(/_/g, " ")}</Badge>
                    {l.job_id ? (
                      <Link href={`/jobs/${encodeURIComponent(l.job_id)}`} className="text-[12px] text-accent-text hover:underline">
                        trace
                      </Link>
                    ) : null}
                  </li>
                ))}
              </ul>
            </Section>
            <Section title="Approval queue" description="Keyboard first: a / s / r on the selected item.">
              <ApprovalQueue runId={r.id} queue={r.queue} />
            </Section>
          </>
        )}
      </Container>
    </>
  );
}
