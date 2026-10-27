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
import { ModeBadge } from "@/components/ui/provenance";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { toast } from "@/components/ui/toast";
import { AdminAccess, AdminLock, useAdmin } from "@/components/admin-access";
import { api } from "@/lib/api";
import type { SteerLane, SteerQueueItem } from "@/lib/api-types";
import { fmtNum, timeAgo, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

function laneTone(l: SteerLane): "ok" | "warn" | "bad" | "accent" | "neutral" {
  if (l.status === "failed") return "bad";
  if (l.status === "running") return "accent";
  if (l.status === "done") return l.verified ? "ok" : "warn";
  return "neutral";
}

const QUEUE_TONE: Record<SteerQueueItem["status"], "ok" | "warn" | "bad" | "accent" | "neutral" | "info"> = {
  building: "accent",
  pending_review: "info",
  published: "ok",
  sent_back: "warn",
  rejected: "neutral",
  failed: "bad",
};

function ApprovalQueue({ runId, items }: { runId: string; items: SteerQueueItem[] }) {
  const qc = useQueryClient();
  const queue = items.filter((q) => q.status === "pending_review");
  const [sel, setSel] = React.useState(0);
  const [note, setNote] = React.useState("");
  const review = useMutation({
    mutationFn: (v: { slug: string; action: "approve" | "send_back" | "reject" }) => api.steerReview(runId, { ...v, note }),
    onSuccess: (state, v) => {
      qc.setQueryData(["steer", runId], state);
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

  if (!queue.length)
    return (
      <EmptyState compact icon={Check} title="Nothing waiting for review">
        {items.length ? "Every built part has been reviewed." : "Parts appear here as their lanes finish building."}
      </EmptyState>
    );
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface" role="listbox" tabIndex={0} aria-label="Approval queue (j/k to move, a approve, s send back, r reject)" aria-activedescendant={cur ? `q-${cur.slug}` : undefined}>
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
            <span className="hidden max-w-[40%] truncate font-mono text-[12px] text-muted md:block">
              {Object.entries(q.params).slice(0, 3).map(([k, v]) => `${k}=${fmtNum(v, 1)}`).join(" ")}
            </span>
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
  const { admin } = useAdmin();
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
    refetchInterval: (q) => (q.state.data && ["done", "failed"].includes(q.state.data.status) ? false : 2500),
  });
  const r = run.data;
  const runs = useQuery({ queryKey: ["steer-runs"], queryFn: () => api.steerRuns(10), enabled: !runId });
  const built = r ? r.lanes.filter((l) => l.status === "done").length : 0;
  const verified = r ? r.lanes.filter((l) => l.verified).length : 0;

  return (
    <>
      <PageHeader
        eyebrow="Factory"
        title="A family of parts from one line"
        description="Write a brief. A planner model proposes the family, builder agents make each part, the verifier measures every one, and you approve what gets published."
      />
      <Container className="space-y-12 py-8">
        {!admin ? <AdminAccess what="Planning a new kit and approving parts for the registry need an admin token. Everyone can watch runs, lanes and reviews." /> : null}
        {admin ? (
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
              <Input id="count" type="number" min={1} max={24} value={count} onChange={(e) => setCount(Math.max(1, Math.min(24, Number(e.target.value) || 1)))} className="w-20 font-mono tnum" />
            </div>
            <Button type="submit" variant="primary" disabled={!brief.trim() || start.isPending}>
              {start.isPending ? <Spinner className="text-accent-fg" label="Planning" /> : <Send aria-hidden />} Plan and build
            </Button>
          </div>
          {start.isError ? <ErrorState error={start.error} compact what="the steer run" /> : null}
          <AdminLock />
        </form>
        ) : null}

        {!runId ? (
          runs.data?.length ? (
            <Section title="Recent runs">
              <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface">
                {runs.data.map((x) => (
                  <li key={x.id}>
                    <Link href={`${pathname}?id=${encodeURIComponent(x.id)}`} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 hover:bg-surface-2">
                      <div className="min-w-0 basis-full sm:basis-0 sm:flex-1">
                        <div className="truncate text-[14px] font-medium">{x.brief}</div>
                        <div className="text-[12px] text-subtle">
                          {x.family_title ? `${x.family_title} · ` : ""}
                          {timeAgo(x.created_at)}
                        </div>
                      </div>
                      <span className="font-mono text-[12px] text-muted tnum">
                        {x.published}/{x.count} published · {x.pending} pending
                      </span>
                      <Badge tone="neutral">{x.status}</Badge>
                    </Link>
                  </li>
                ))}
              </ul>
            </Section>
          ) : (
            <EmptyState icon={Factory} title="No runs yet">
              Start a run above. Each part goes through the same verifier as a photo fix; nothing is published without approval.
            </EmptyState>
          )
        ) : run.isError ? (
          <ErrorState error={run.error} what="this run" onRetry={() => void run.refetch()} />
        ) : !r ? (
          <Skeleton className="h-64" />
        ) : (
          <>
            <div className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-5 md:flex-row md:items-end md:justify-between">
              <div className="min-w-0 space-y-1.5">
                <div className="flex flex-wrap items-center gap-1.5 text-[12px] text-muted">
                  <span className="font-mono">{r.id}</span>
                  <Badge tone={r.status === "failed" ? "bad" : r.status === "done" ? "ok" : "accent"}>{r.status}</Badge>
                  {r.planner ? (
                    <Badge tone="neutral" className="font-mono">
                      planner {r.planner.model}
                    </Badge>
                  ) : null}
                  {r.planner ? <ModeBadge mode={r.planner.mode} hideLive /> : null}
                  {r.label ? <Badge tone="mock">{r.label}</Badge> : null}
                </div>
                <h2 className="text-[20px] leading-tight font-semibold tracking-tight">{r.family_title || r.brief}</h2>
                {r.family_title ? <p className="text-[13px] text-muted">“{r.brief}”</p> : null}
              </div>
              <dl className="flex shrink-0 gap-6 font-mono tnum">
                <div>
                  <dt className="font-sans text-[11px] text-subtle">built</dt>
                  <dd className="text-[18px]">
                    {built}/{r.lanes.length}
                  </dd>
                </div>
                <div>
                  <dt className="font-sans text-[11px] text-subtle">self-check passed</dt>
                  <dd className="text-[18px]">
                    {verified}/{r.lanes.length}
                  </dd>
                </div>
                <div>
                  <dt className="font-sans text-[11px] text-subtle">published</dt>
                  <dd className="text-[18px]">{r.queue.filter((q) => q.status === "published").length}</dd>
                </div>
              </dl>
            </div>
            <p className="-mt-6 text-[12px] leading-5 text-subtle">
              Lanes verify each part against its own rendered silhouette — a synthetic self-check, not a photo measurement.
            </p>
            {r.plan_notes.length ? (
              <ul className="list-disc space-y-1 pl-5 text-[13px] text-muted">
                {r.plan_notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            ) : null}
            <Section title="Plan">
              <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {r.plan.map((p) => (
                  <li key={p.slug} className="space-y-1.5 rounded-lg border border-border bg-surface p-3.5">
                    <div className="flex items-start justify-between gap-2">
                      <div className="text-[13.5px] font-medium">{p.title}</div>
                      <Badge tone="neutral">{titleCase(p.family)}</Badge>
                    </div>
                    {p.why ? <p className="text-[12px] leading-5 text-muted">{p.why}</p> : null}
                    <p className="font-mono text-[11px] leading-4 break-words text-subtle">
                      {Object.entries(p.params)
                        .map(([k, v]) => `${k}=${fmtNum(v, Number.isInteger(v) ? 0 : 2)}`)
                        .join("  ")}
                    </p>
                  </li>
                ))}
              </ul>
            </Section>
            <Section title="Build lanes">
              <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface">
                {r.lanes.map((l) => (
                  <li key={l.slug} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-[13px]">
                    <span className="min-w-0 flex-1 truncate font-mono">{l.slug}</span>
                    {l.error ? <span className="w-full truncate text-[12px] text-bad sm:order-none sm:w-auto">{l.error}</span> : null}
                    {l.max_error_mm != null ? <span className="font-mono text-[12px] text-muted tnum">{fmtNum(l.max_error_mm)} mm</span> : null}
                    <Badge tone={laneTone(l)}>
                      {l.status === "running" ? <Spinner className="size-3 text-current" label="Building" /> : null}
                      {l.status === "done" ? (l.verified ? "self-check passed" : "best effort") : l.status}
                    </Badge>
                    {l.job_id ? (
                      <Link href={`/jobs/${encodeURIComponent(l.job_id)}`} className="text-[12px] text-accent-text hover:underline">
                        trace
                      </Link>
                    ) : null}
                  </li>
                ))}
              </ul>
            </Section>
            <Section title="Approval queue" description="Keyboard first: a approve · s send back with your note · r reject.">
              {admin ? (
                <ApprovalQueue runId={r.id} items={r.queue} />
              ) : (
                <ul className="flex flex-wrap gap-1.5" aria-label="Review queue (read-only)">
                  {r.queue.map((q) => (
                    <li key={q.slug}>
                      <Badge tone={QUEUE_TONE[q.status]}>
                        {q.title} · {q.status.replace("_", " ")}
                      </Badge>
                    </li>
                  ))}
                  {r.queue.length === 0 ? <li className="text-[13px] text-muted">Nothing in the queue yet.</li> : null}
                </ul>
              )}
              {r.queue.some((q) => q.status !== "pending_review") ? (
                <ul className="flex flex-wrap gap-1.5">
                  {r.queue
                    .filter((q) => q.status !== "pending_review")
                    .map((q) => (
                      <li key={q.slug}>
                        <Badge tone={QUEUE_TONE[q.status]}>
                          {q.title} · {q.status.replace("_", " ")}
                        </Badge>
                      </li>
                    ))}
                </ul>
              ) : null}
            </Section>
            {r.history.length ? (
              <Section title="Review history">
                <ol className="space-y-1.5 text-[13px]">
                  {[...r.history].reverse().map((h, i) => (
                    <li key={i} className="flex flex-wrap items-baseline gap-x-2">
                      <span className="font-mono text-[12px] text-subtle">{timeAgo(h.ts)}</span>
                      <span className="font-medium">{h.action.replace("_", " ")}</span>
                      <span className="font-mono text-[12px]">{h.slug}</span>
                      {h.note ? <span className="text-muted">“{h.note}”</span> : null}
                      {h.applied?.length ? <span className="text-ok">applied: {h.applied.join(", ")}</span> : null}
                      {h.not_applied?.length ? <span className="text-warn">not applied: {h.not_applied.join(", ")}</span> : null}
                    </li>
                  ))}
                </ol>
              </Section>
            ) : null}
          </>
        )}
      </Container>
    </>
  );
}
