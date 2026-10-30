"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpenCheck, Check, Lightbulb, X } from "lucide-react";
import Link from "next/link";
import { Container, PageHeader, Section } from "@/components/layout/page";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { AdminAccess, useAdmin } from "@/components/admin-access";
import { Button } from "@/components/ui/button";
import { decideLesson, lessons, R2, type Lesson } from "@/lib/api-r2";
import { useCapabilities } from "@/lib/capabilities";
import { timeAgo, titleCase } from "@/lib/format";
import { trackText } from "@/lib/review";

function evidenceFacts(ev: Record<string, unknown>): string[] {
  const skip = new Set(["job_id", "job_ids", "slug", "part_slug", "fit_report_ids"]);
  return Object.entries(ev)
    .filter(([k, v]) => !skip.has(k) && (typeof v === "number" || typeof v === "string" || typeof v === "boolean"))
    .slice(0, 6)
    .map(([k, v]) => `${k.replaceAll("_", " ")}: ${typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(2)) : String(v)}`);
}

function LessonCard({ l, admin }: { l: Lesson; admin: boolean }) {
  const qc = useQueryClient();
  const decide = useMutation({
    mutationFn: (a: "promote" | "reject") => decideLesson(l.id, a),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["lessons"] }),
  });
  const facts = evidenceFacts(l.evidence);
  const track = trackText(l.track);
  return (
    <li className="space-y-2 rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone={l.status === "promoted" ? "ok" : l.status === "candidate" ? "accent" : "neutral"}>{l.status}</Badge>
        <Badge tone="neutral">{l.scope === "global" ? "All parts" : titleCase(l.scope)}</Badge>
        {l.created_at ? <span className="text-[11.5px] text-subtle">{timeAgo(l.created_at)}</span> : null}
        {l.promoted_by && l.status !== "candidate" ? <span className="text-[11.5px] text-subtle">· by {l.promoted_by}</span> : null}
      </div>
      <p className="text-[14px] leading-6 text-fg">{l.rule}</p>
      {facts.length ? <p className="font-mono text-[11.5px] leading-5 text-muted tnum">{facts.join(" · ")}</p> : null}
      {track ? (
        <p className="text-[12px] leading-5 text-muted tnum">{track}</p>
      ) : null}
      {l.links.length ? (
        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[12px]" aria-label="Evidence">
          {l.links.map((e) => (
            <li key={`${e.kind}-${e.id}`}>
              <span className="text-subtle">{e.kind.replace("_", " ")} </span>
              {e.page ? (
                <Link href={e.page} className="font-mono text-accent-text hover:underline">
                  {e.id}
                </Link>
              ) : (
                <span className="font-mono">{e.id}</span>
              )}
            </li>
          ))}
        </ul>
      ) : null}
      {admin && l.status === "candidate" ? (
        <div className="flex gap-2 pt-1">
          <Button size="sm" variant="outline" disabled={decide.isPending} onClick={() => decide.mutate("promote")}>
            <Check aria-hidden /> Promote
          </Button>
          <Button size="sm" variant="ghost" disabled={decide.isPending} onClick={() => decide.mutate("reject")}>
            <X aria-hidden /> Reject
          </Button>
        </div>
      ) : null}
      {decide.isError ? <ErrorState error={decide.error} compact what="the decision" /> : null}
    </li>
  );
}

/** Candidate vs promoted lessons with the runs that support them. Shown only when this API serves `/lessons`. */
export function LessonsClient() {
  const caps = useCapabilities();
  const { admin } = useAdmin();
  const available = caps.has("get", R2.lessons);
  const q = useQuery({ queryKey: ["lessons"], queryFn: lessons, enabled: available });
  const promoted = q.data?.filter((l) => l.status === "promoted") ?? [];
  const candidates = q.data?.filter((l) => l.status === "candidate") ?? [];
  const rejected = q.data?.filter((l) => l.status === "rejected") ?? [];
  return (
    <>
      <PageHeader
        eyebrow="Lessons"
        title="What the builder learned"
        description="Each finished run can suggest a lesson, with the run, part or fit report that backs it. A person promotes it; only promoted lessons reach future builds."
      />
      <Container className="space-y-12 py-8">
        {!caps.ready ? (
          <Skeleton className="h-40" />
        ) : !available ? (
          <EmptyState icon={Lightbulb} title="Lessons are not available on this server yet">
            This API does not serve a lessons list. Nothing is shown rather than an example.
          </EmptyState>
        ) : q.isPending ? (
          <Skeleton className="h-40" />
        ) : q.isError ? (
          <ErrorState error={q.error} what="lessons" onRetry={() => void q.refetch()} />
        ) : (
          <>
            <Section title={`Promoted (${promoted.length})`} description="Fed to the builder on new runs in their scope.">
              {promoted.length ? (
                <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">{promoted.map((l) => <LessonCard key={l.id} l={l} admin={admin} />)}</ul>
              ) : (
                <EmptyState compact icon={BookOpenCheck} title="None promoted yet" />
              )}
            </Section>
            <Section title={`Candidates (${candidates.length})`} description="Suggested by a run; waiting for a person to promote or reject.">
              {candidates.length ? (
                <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">{candidates.map((l) => <LessonCard key={l.id} l={l} admin={admin} />)}</ul>
              ) : (
                <EmptyState compact icon={Lightbulb} title="No candidates right now" />
              )}
            </Section>
            {rejected.length ? (
              <Section title={`Rejected (${rejected.length})`} description="Kept for the record; never used.">
                <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">{rejected.map((l) => <LessonCard key={l.id} l={l} admin={admin} />)}</ul>
              </Section>
            ) : null}
            {!admin && candidates.length ? <AdminAccess what="Promoting or rejecting a lesson needs an admin token." /> : null}
          </>
        )}
      </Container>
    </>
  );
}
