"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpenCheck, Check, Lightbulb, X } from "lucide-react";
import Link from "next/link";
import * as React from "react";
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
import { PRODUCT, productApi } from "@/lib/api-product";
import { buildsUsing, groupLessons, groupLinks, humanName, knobRuns, lessonConflict, lessonText, type LessonGroup } from "@/lib/page-groups";
import { trackText } from "@/lib/review";

/** Evidence worth a line under the rule; a knob lesson's template, knob and values are already in its wording. */
function evidenceFacts(ev: Record<string, unknown>): string[] {
  const skip = new Set(["job_id", "job_ids", "slug", "part_slug", "fit_report_ids", ...(typeof ev.param === "string" ? ["template", "param", "first", "final"] : [])]);
  return Object.entries(ev)
    .filter(([k, v]) => !skip.has(k) && (typeof v === "number" || typeof v === "string" || typeof v === "boolean"))
    .slice(0, 6)
    .map(([k, v]) => `${k.replaceAll("_", " ").replace(/ mm$/, "")}: ${typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(2)) + (k.endsWith("_mm") ? " mm" : "") : typeof v === "boolean" ? (v ? "yes" : "no") : String(v).replaceAll("_", " ")}`);
}

/** Knob labels from each template's PARAMS ("cable_clip.hole_d" → "Hole diameter"), when this server lists templates. */
function useKnobLabels(): (template: unknown, param: unknown) => string | undefined {
  const caps = useCapabilities();
  const t = useQuery({ queryKey: ["templates"], queryFn: productApi.templates, enabled: caps.has("get", PRODUCT.templates), staleTime: 300_000, retry: false });
  const map = React.useMemo(() => new Map((t.data ?? []).flatMap((c) => c.params.filter((p) => p.label).map((p) => [`${c.name}.${p.name}`, p.label] as const))), [t.data]);
  return (template, param) => (typeof template === "string" && typeof param === "string" ? map.get(`${template}.${param}`) : undefined);
}

function Decide({ l }: { l: Lesson }) {
  const qc = useQueryClient();
  const decide = useMutation({
    mutationFn: (a: "promote" | "reject") => decideLesson(l.id, a),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["lessons"] }),
  });
  return (
    <>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" disabled={decide.isPending} onClick={() => decide.mutate("promote")}>
          <Check aria-hidden /> Promote
        </Button>
        <Button size="sm" variant="ghost" disabled={decide.isPending} onClick={() => decide.mutate("reject")}>
          <X aria-hidden /> Reject
        </Button>
      </div>
      {decide.isError ? <ErrorState error={decide.error} compact what="the decision" /> : null}
    </>
  );
}

const MAX_LINKS = 6;

/** One card per group of lessons that say the same thing; the newest wording leads, the others fold away. */
function LessonCard({ g, admin, knobLabel }: { g: LessonGroup<Lesson>; admin: boolean; knobLabel: (template: unknown, param: unknown) => string | undefined }) {
  const l = g.lead;
  const label = knobLabel(l.evidence.template, l.evidence.param);
  const n = g.members.length;
  const facts = evidenceFacts(l.evidence);
  const track = trackText(l.track);
  const used = (l.track?.used_in ?? 0) > 0 || l.status === "promoted";
  const runs = n > 1 ? knobRuns(g.members) : [];
  // a run listed with its values above is not listed again as an evidence link
  const links = groupLinks(g.members).filter((e) => e.kind !== "job" || !runs.some((r) => r.job === e.id));
  const knob = label || (typeof l.evidence.param === "string" ? humanName(l.evidence.param) : "value");
  const builds = buildsUsing(g.members);
  const conflict = lessonConflict(g.members);
  return (
    <li className="space-y-2 rounded-lg border border-border bg-surface p-4" data-testid="lesson-card">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone={l.status === "promoted" ? "ok" : l.status === "candidate" ? "accent" : "neutral"}>{l.status}</Badge>
        {conflict ? <Badge tone="warn">conflicting evidence</Badge> : null}
        {n > 1 ? <Badge tone="info">suggested by {n} runs</Badge> : null}
        <Badge tone="neutral" className="tnum" data-testid="lesson-builds">
          used in {builds} build{builds === 1 ? "" : "s"}
        </Badge>
        {l.created_at ? <span className="text-[11.5px] text-subtle">{n > 1 ? "newest " : ""}{timeAgo(l.created_at)}</span> : null}
        {l.promoted_by && l.status !== "candidate" ? <span className="text-[11.5px] text-subtle">· by {l.promoted_by}</span> : null}
      </div>
      {conflict ? (
        <p className="text-[14px] leading-6 text-fg">
          The runs disagree on {knob}: {conflict.up} moved it up and {conflict.down} moved it down. This is not advice; a person should look at these runs before anything is promoted.
        </p>
      ) : (
        <p className="text-[14px] leading-6 text-fg">{lessonText(l, label)}</p>
      )}
      {runs.length ? (
        <div className="space-y-1" data-testid="knob-runs">
          <p className="text-[12px] text-muted">
            {knob} in each run, first build → final{runs.length < n ? ` (${runs.length} of ${n} runs record it)` : ""}:
          </p>
          <ul className="space-y-0.5 font-mono text-[11.5px] leading-6 tnum">
            {runs.map((r) => (
              <li key={r.id} className="flex flex-wrap items-baseline gap-x-2">
                {r.page ? (
                  <Link href={r.page} className="text-accent-text hover:underline">
                    {r.job}
                  </Link>
                ) : (
                  <span className="text-muted">{r.job ?? r.id}</span>
                )}
                <span className="text-fg">
                  {String(Number(r.first.toFixed(2)))} → {String(Number(r.final.toFixed(2)))}
                </span>
                <span className="text-subtle">
                  {r.verified === true ? "verified" : r.verified === false ? "best effort" : ""}
                  {r.maxErrorMm != null ? ` · max gap ${r.maxErrorMm.toFixed(2)} mm` : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : facts.length ? (
        <p className="font-mono text-[11.5px] leading-5 text-muted tnum">{facts.join(" · ")}</p>
      ) : null}
      {track && used ? <p className="text-[12px] leading-5 text-muted tnum">{track}</p> : null}
      {links.length ? (
        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[12px]" aria-label="Evidence">
          {links.slice(0, MAX_LINKS).map((e) => (
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
          {links.length > MAX_LINKS ? <li className="text-subtle">+{links.length - MAX_LINKS} more</li> : null}
        </ul>
      ) : null}
      {admin && l.status === "candidate" ? (
        <div className="pt-1">
          <Decide l={l} />
        </div>
      ) : null}
      {n > 1 ? (
        <details className="text-[12.5px]">
          <summary className="cursor-pointer text-muted select-none hover:text-fg">Every wording ({n})</summary>
          <ul className="mt-2 space-y-2 border-l border-border pl-3">
            {g.members.map((m) => (
              <li key={m.id} className="space-y-1">
                <p className="leading-5 text-muted">{lessonText(m, label)}</p>
                <p className="text-[11.5px] text-subtle">
                  <span className="font-mono">{m.id}</span>
                  {m.created_at ? ` · ${timeAgo(m.created_at)}` : ""}
                </p>
                {admin && m.status === "candidate" && m.id !== l.id ? <Decide l={m} /> : null}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </li>
  );
}

const PER_FAMILY = 3;
const OPEN_FAMILIES = 3;

/**
 * Lessons of one status, one block per family (largest first). The first few families start open with their first
 * few cards; the rest start folded to a heading, so a long list stays scannable.
 */
function FamilyGroups({ list, admin, label }: { list: Lesson[]; admin: boolean; label: string }) {
  const families = React.useMemo(() => groupLessons(list), [list]);
  const knobLabel = useKnobLabels();
  const [toggled, setToggled] = React.useState<Set<string>>(() => new Set());
  const [all, setAll] = React.useState<Set<string>>(() => new Set());
  const flip = (set: React.Dispatch<React.SetStateAction<Set<string>>>, k: string) =>
    set((s) => {
      const next = new Set(s);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  return (
    <div className="space-y-5">
      {families.map((f, i) => {
        const open = (i < OPEN_FAMILIES) !== toggled.has(f.scope);
        const showAll = all.has(f.scope);
        // runs that pushed a knob both ways are folded apart under one note, never shown as advice
        const advice = f.groups.filter((g) => !lessonConflict(g.members));
        const conflicts = f.groups.filter((g) => lessonConflict(g.members));
        const shown = showAll ? advice : advice.slice(0, PER_FAMILY);
        const id = `${label}-${f.scope}`;
        return (
          <section key={f.scope} aria-labelledby={id} className="space-y-2.5">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border pb-1.5">
              <h3 id={id} className="flex flex-wrap items-baseline gap-2 text-[14px] font-semibold">
                {f.scope === "global" ? "All parts" : titleCase(f.scope)}
                <span className="text-[12px] font-normal text-subtle tnum">
                  {f.groups.length} card{f.groups.length === 1 ? "" : "s"}
                  {f.lessons > f.groups.length ? ` from ${f.lessons} suggestions` : ""}
                </span>
              </h3>
              <Button variant="ghost" size="sm" className="ml-auto" aria-expanded={open} aria-controls={`${id}-cards`} onClick={() => flip(setToggled, f.scope)}>
                {open ? "Fold" : "Show"}
              </Button>
            </div>
            {open ? (
              <div id={`${id}-cards`} className="space-y-2.5">
                {shown.length ? (
                  <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
                    {shown.map((g) => (
                      <LessonCard key={g.key} g={g} admin={admin} knobLabel={knobLabel} />
                    ))}
                  </ul>
                ) : null}
                {advice.length > PER_FAMILY ? (
                  <Button variant="ghost" size="sm" aria-expanded={showAll} onClick={() => flip(setAll, f.scope)}>
                    {showAll ? "Show fewer" : `Show all ${advice.length}`}
                  </Button>
                ) : null}
                {conflicts.length ? (
                  <details className="rounded-lg border border-warn-border bg-warn-soft/40 px-3 py-2" data-testid="lesson-conflicts">
                    <summary className="cursor-pointer text-[13px] font-medium select-none">
                      Conflicting evidence: {conflicts.length} knob{conflicts.length === 1 ? "" : "s"} where runs moved the value in opposite directions (not advice)
                    </summary>
                    <ul className="mt-2.5 grid grid-cols-1 gap-3 md:grid-cols-2">
                      {conflicts.map((g) => (
                        <LessonCard key={g.key} g={g} admin={admin} knobLabel={knobLabel} />
                      ))}
                    </ul>
                  </details>
                ) : null}
              </div>
            ) : null}
          </section>
        );
      })}
    </div>
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
  const unusedCandidates = candidates.length > 0 && candidates.every((l) => (l.track?.used_in ?? 0) === 0);
  const promotedSection = (
    <Section key="promoted" title={`Promoted (${promoted.length})`} description="Fed to the builder on new runs in their scope.">
      {promoted.length ? (
        <FamilyGroups list={promoted} admin={admin} label="promoted" />
      ) : (
        <EmptyState compact icon={BookOpenCheck} title="None promoted yet">
          A person promotes a candidate once its evidence holds up. Until then no lesson reaches a build.
        </EmptyState>
      )}
    </Section>
  );
  const candidatesSection = (
    <Section
      key="candidates"
      title={`Candidates (${candidates.length})`}
      description={`Suggested by a run; waiting for a person to promote or reject.${unusedCandidates ? " None has been used in a job yet: only promoted lessons reach builds." : ""} Suggestions that say the same thing share one card.`}
    >
      {candidates.length ? (
        <FamilyGroups list={candidates} admin={admin} label="candidates" />
      ) : (
        <EmptyState compact icon={Lightbulb} title="No candidates right now" />
      )}
    </Section>
  );
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
            {/* Work waiting for a person leads while nothing is promoted yet. */}
            {promoted.length ? [promotedSection, candidatesSection] : [candidatesSection, promotedSection]}
            {rejected.length ? (
              <Section title={`Rejected (${rejected.length})`} description="Kept for the record; never used.">
                <FamilyGroups list={rejected} admin={admin} label="rejected" />
              </Section>
            ) : null}
            {!admin && candidates.length ? <AdminAccess what="Promoting or rejecting a lesson needs an admin token." /> : null}
          </>
        )}
      </Container>
    </>
  );
}
