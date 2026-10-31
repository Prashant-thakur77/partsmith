"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ClipboardCheck, ExternalLink, History, Users, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import dynamic from "next/dynamic";
import { AdminAccess, AdminLock, useAdmin } from "@/components/admin-access";
import { ExportMenu } from "@/components/jobs/export-menu";
import { PhotoPanel, imagesByView } from "@/components/jobs/photo-panel";
import { Container, PageHeader } from "@/components/layout/page";
import { DecisionBar, MAX_ATTACHMENTS, type Attachment } from "@/components/review/decision-bar";
import { JudgeScorecard } from "@/components/review/judge-scorecard";
import { MeasureCheck } from "@/components/review/measure-check";
import { PinPhoto } from "@/components/review/pin-photo";
import { RoundHistory } from "@/components/review/round-history";
import { RoundStrip } from "@/components/review/round-strip";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/card";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input, Label, Textarea } from "@/components/ui/input";
import { OriginBadge } from "@/components/ui/provenance";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { toast } from "@/components/ui/toast";
import { Switch } from "@/components/ui/toggle";
import { api, apiUrl, request } from "@/lib/api";
import { REVIEW, review, type DecisionBody } from "@/lib/api-review";
import { ReviewQueueSchema, type ArtifactEvent, type ReviewQueueItem, type ReviewVerdict } from "@/lib/api-types";
import { useCapabilities } from "@/lib/capabilities";
import { fmtUsd, timeAgo, titleCase } from "@/lib/format";
import {
  agentRows,
  agreementText,
  blocker,
  decisionBody,
  reviewersLabel,
  roundLabel,
  scorecardSummary,
  sortQueue,
  verdictText,
  verdictTone,
  type DraftPin,
} from "@/lib/review";
import { cn } from "@/lib/utils";

const CadViewer = dynamic(() => import("@/components/viewer/cad-viewer").then((m) => m.CadViewer), {
  ssr: false,
  loading: () => (
    <div role="status" aria-label="Loading the 3D viewer" className="relative h-[420px]">
      <Skeleton className="absolute inset-0 rounded-none" />
    </div>
  ),
});

type Tone = "ok" | "warn" | "bad" | "accent" | "neutral" | "info";
const STATUS_TONE: Record<string, Tone> = { waiting: "warn", improving: "accent", accepted: "ok", rejected: "neutral" };
const STATUS_TEXT: Record<string, string> = { waiting: "waiting", improving: "round running", accepted: "accepted", rejected: "rejected" };

/** Keys typed into a field, a dialog, or with a modifier never trigger review shortcuts. */
function ignoreKey(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  return !!t?.closest?.("input, textarea, select, [contenteditable], [role=dialog]") || e.metaKey || e.ctrlKey || e.altKey;
}

function StatsStrip() {
  const caps = useCapabilities();
  const stats = useQuery({ queryKey: ["review", "stats"], queryFn: review.stats, enabled: caps.has("get", REVIEW.stats), retry: false });
  const text = agreementText(stats.data);
  if (!text || !stats.data) return null;
  return (
    <div role="note" aria-label="Judge and reviewer agreement" className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface px-4 py-2.5 text-[13px]">
      <Users className="size-4 text-muted" aria-hidden />
      <span className="font-medium tnum">{text}</span>
      <Badge tone="neutral">{reviewersLabel(stats.data.reviewers)}</Badge>
      <span className="text-[12px] text-subtle">
        Counted from saved reviews that have a judge scorecard
        {stats.data.tests_excluded ? `; ${stats.data.tests_excluded} test review${stats.data.tests_excluded === 1 ? "" : "s"} not counted` : ""}.
      </span>
    </div>
  );
}

function QueueList({ items, selected, onSelect }: { items: ReviewQueueItem[]; selected: string | null; onSelect: (id: string) => void }) {
  return (
    <ul
      className="max-h-[340px] divide-y divide-border overflow-y-auto rounded-lg border border-border bg-surface lg:max-h-[calc(100dvh-160px)]"
      role="listbox"
      tabIndex={0}
      aria-label="Review queue (j/k to move)"
      aria-activedescendant={selected ? `rq-${selected}` : undefined}
    >
      {items.map((q) => {
        const on = q.job_id === selected;
        return (
          <li
            key={q.job_id}
            id={`rq-${q.job_id}`}
            role="option"
            aria-selected={on}
            onClick={() => onSelect(q.job_id)}
            className={cn("flex cursor-pointer gap-3 px-3 py-3", on ? "bg-accent-soft" : "hover:bg-surface-2")}
          >
            <span className={cn("w-0.5 shrink-0 rounded-full", on ? "bg-accent" : "bg-transparent")} aria-hidden />
            <div className="min-w-0 flex-1 space-y-1.5">
              <div className="truncate text-[14px] font-medium">{q.title || q.job_id}</div>
              <div className="flex flex-wrap items-center gap-1">
                <Badge tone={STATUS_TONE[q.status] ?? "neutral"}>{STATUS_TEXT[q.status] ?? q.status}</Badge>
                <Badge tone="outline">{roundLabel(q.round)}</Badge>
                <Badge tone={verdictTone(q.verdict)} className="font-mono tnum">
                  {verdictText(q.verdict)}
                </Badge>
                {q.judge?.mode && q.judge.mode !== "live" ? <Badge tone="mock">judge {q.judge.mode}</Badge> : null}
                {q.is_replay ? <Badge tone="mock">replay</Badge> : null}
                <span className="font-mono text-[11.5px] text-muted tnum">{fmtUsd(q.cost_usd)}</span>
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function AgentsCard({ jobId, costUsd }: { jobId: string; costUsd: number | null | undefined }) {
  const job = useQuery({ queryKey: ["job", jobId], queryFn: () => api.job(jobId) });
  const rows = React.useMemo(() => agentRows(job.data?.events ?? []), [job.data?.events]);
  const total = costUsd ?? job.data?.summary.cost_usd ?? null;
  return (
    <section className="space-y-2 rounded-lg border border-border bg-surface p-4" aria-label="What each agent did">
      <div className="flex items-center justify-between gap-2">
        <Eyebrow>Agents and cost</Eyebrow>
        <span className="font-mono text-[12px] text-muted tnum">total {fmtUsd(total)}</span>
      </div>
      {job.isPending ? (
        <Skeleton className="h-16" />
      ) : job.isError ? (
        <ErrorState error={job.error} compact what="this job's trace" />
      ) : rows.length ? (
        <table className="w-full table-fixed font-mono text-[12px] tnum">
          <caption className="sr-only">Model calls by stage</caption>
          <thead>
            <tr className="text-left text-[11px] text-subtle">
              <th scope="col" className="w-[34%] py-1 font-sans font-medium">Stage</th>
              <th scope="col" className="py-1 font-sans font-medium">Model</th>
              <th scope="col" className="w-12 py-1 text-right font-sans font-medium">Calls</th>
              <th scope="col" className="w-16 py-1 text-right font-sans font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.stage}-${r.model}`} className="border-t border-border">
                <th scope="row" className="truncate py-1.5 pr-2 text-left font-sans font-normal" title={r.stage}>{r.stage}</th>
                <td className="truncate py-1.5 pr-2" title={r.model}>
                  {r.model.replace(/^meta-models\//, "")}
                  {r.mode !== "live" ? <span className="text-subtle"> ({r.mode})</span> : null}
                </td>
                <td className="py-1.5 text-right">
                  {r.calls}
                  {r.failed ? <span className="text-bad"> ({r.failed} failed)</span> : null}
                </td>
                <td className="py-1.5 text-right">{fmtUsd(r.usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-[13px] text-muted">No model calls in this job&apos;s events.</p>
      )}
      <Link href={`/jobs/${encodeURIComponent(jobId)}`} className="inline-flex items-center gap-1 text-[12px] text-accent-text hover:underline">
        <ExternalLink className="size-3.5" aria-hidden /> Open the full trace
      </Link>
    </section>
  );
}

type RuleRow = { text: string; keep: boolean; source_pin: number | null; scope: string };

function AcceptDialog({
  open,
  onOpenChange,
  jobId,
  family,
  isReplay,
  verdict,
  pending,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  jobId: string;
  family: string;
  isReplay: boolean;
  verdict: ReviewVerdict | null | undefined;
  pending: boolean;
  onConfirm: (rules: RuleRow[], publish: boolean) => void;
}) {
  const draft = useQuery({ queryKey: ["review", "draft", jobId], queryFn: () => review.draftRules(jobId), enabled: open, staleTime: Infinity, retry: false });
  const [rules, setRules] = React.useState<RuleRow[]>([]);
  const [publish, setPublish] = React.useState(false);
  React.useEffect(() => {
    if (draft.data) setRules(draft.data.rules.map((r) => ({ text: r.text, keep: true, source_pin: r.source_pin ?? null, scope: r.scope })));
  }, [draft.data]);
  const set = (i: number, patch: Partial<RuleRow>) => setRules((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const passed = verdict?.status === "verified";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <div className="space-y-1.5 pr-8">
          <DialogTitle>Accept this part</DialogTitle>
          <DialogDescription>Your sign-off is saved next to the code&apos;s verdict. It does not change the verdict.</DialogDescription>
        </div>
        {!passed ? (
          <p role="note" className="rounded-md border border-warn-border bg-warn-soft px-3 py-2 text-[13px]">
            The measurements did not pass ({verdictText(verdict)}). It stays best effort. If you publish it, it is labelled best effort, accepted by a person.
          </p>
        ) : null}
        <div className="space-y-2">
          <Eyebrow>Rules for future {family ? titleCase(family) : "parts like this"}</Eyebrow>
          {draft.isPending ? (
            <p className="flex items-center gap-2 text-[13px] text-muted" role="status">
              <Spinner className="size-3.5" label="Drafting" /> Drafting rules from the notes…
            </p>
          ) : draft.isError ? (
            <div className="space-y-1">
              <ErrorState error={draft.error} compact what="the drafted rules" />
              <p className="text-[12px] text-muted">You can still accept without rules.</p>
            </div>
          ) : rules.length ? (
            <>
              <p className="text-[12px] leading-5 text-subtle">Ticked rules are given to the builder on future parts of this kind. Unticked ones stay as suggestions.</p>
              <ul className="space-y-2" aria-label="Drafted rules">
                {rules.map((r, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <input
                      type="checkbox"
                      checked={r.keep}
                      onChange={(e) => set(i, { keep: e.target.checked })}
                      aria-label={`Keep rule ${i + 1}`}
                      className="mt-2.5 size-4 shrink-0 accent-[var(--color-accent)]"
                    />
                    <div className="min-w-0 flex-1 space-y-0.5">
                      <Input aria-label={`Rule ${i + 1}`} value={r.text} maxLength={200} onChange={(e) => set(i, { text: e.target.value })} className="text-[13px]" />
                      <p className="text-[11.5px] text-subtle">
                        {r.source_pin != null ? `from pin ${r.source_pin}` : "from a general note"}
                        {r.scope ? ` · ${r.scope}` : ""}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="text-[13px] text-muted">No notes in this review, so there are no rules to keep.</p>
          )}
        </div>
        {!isReplay ? (
          <div className="space-y-1">
            <Switch label="Publish to the registry" checked={publish} onCheckedChange={setPublish} />
            <p className="text-[12px] text-subtle">Off keeps the sign-off without publishing.</p>
          </div>
        ) : null}
        <div className="flex justify-end gap-2">
          <DialogClose asChild>
            <Button variant="ghost">Cancel</Button>
          </DialogClose>
          <Button variant="primary" disabled={pending || draft.isPending} onClick={() => onConfirm(rules, publish)}>
            {pending ? <Spinner className="text-accent-fg" label="Saving" /> : <Check aria-hidden />} Accept
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function RejectDialog({
  open,
  onOpenChange,
  reason,
  setReason,
  pending,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  reason: string;
  setReason: (v: string) => void;
  pending: boolean;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <div className="space-y-1.5 pr-8">
          <DialogTitle>Reject this part</DialogTitle>
          <DialogDescription>The reason is kept as a lesson suggestion and in the failure list.</DialogDescription>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="reject-reason">Reason</Label>
          <Textarea id="reject-reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={3} maxLength={300} placeholder="e.g. wrong part: this is the left latch, not the right one" autoFocus />
        </div>
        <div className="flex justify-end gap-2">
          <DialogClose asChild>
            <Button variant="ghost">Cancel</Button>
          </DialogClose>
          <Button variant="danger" disabled={pending || !reason.trim()} onClick={onConfirm}>
            {pending ? <Spinner className="text-white" label="Saving" /> : <X aria-hidden />} Reject
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ReviewDetailPanel({ jobId, item, admin }: { jobId: string; item: ReviewQueueItem | undefined; admin: boolean }) {
  const qc = useQueryClient();
  const detail = useQuery({ queryKey: ["review", "detail", jobId], queryFn: () => review.detail(jobId) });
  const job = useQuery({ queryKey: ["job", jobId], queryFn: () => api.job(jobId) });
  const [pins, setPins] = React.useState<DraftPin[]>([]);
  const [note, setNote] = React.useState("");
  const [why, setWhy] = React.useState("");
  const [reason, setReason] = React.useState("");
  const [hint, setHint] = React.useState<string | null>(null);
  const [acceptOpen, setAcceptOpen] = React.useState(false);
  const [rejectOpen, setRejectOpen] = React.useState(false);
  const noteRef = React.useRef<HTMLTextAreaElement>(null);

  const d = detail.data;
  const cur = d?.rounds.at(-1);
  const status = d?.status ?? item?.status ?? "";
  const canAct = admin && !!cur && !cur.decision && status === "waiting";
  const verdict = cur?.verdict ?? item?.verdict;
  const judge = cur?.judge ?? item?.judge ?? job.data?.judge;
  const title = item?.title || job.data?.summary.title || jobId;
  const isReplay = item?.is_replay ?? job.data?.summary.is_replay ?? false;
  const family = item?.family || job.data?.partspec?.family || "";
  const earlier = React.useMemo(() => (d ? d.rounds.slice(0, -1).flatMap((r) => r.pins) : []), [d]);
  const [attachments, setAttachments] = React.useState<Attachment[]>([]);
  const nextAttachment = React.useRef(1);
  const keys = attachments.flatMap((a) => (a.key ? [a.key] : []));
  const addImages = React.useCallback(
    (files: File[]) => {
      if (!cur) return;
      const room = MAX_ATTACHMENTS - attachments.length;
      if (room <= 0) {
        toast(`At most ${MAX_ATTACHMENTS} pictures per decision`, { tone: "info" });
        return;
      }
      for (const f of files.slice(0, room)) {
        const id = nextAttachment.current++;
        setAttachments((xs) => [...xs, { id, preview: URL.createObjectURL(f), key: null, error: null }]);
        review
          .uploadAttachment(cur.job_id, f, f.name || "screenshot.png")
          .then((res) => setAttachments((xs) => xs.map((a) => (a.id === id ? { ...a, key: res.key } : a))))
          .catch((e: unknown) =>
            setAttachments((xs) => xs.map((a) => (a.id === id ? { ...a, error: e instanceof Error ? e.message.slice(0, 60) : "upload failed" } : a))),
          );
      }
      setHint(null);
    },
    [cur, attachments.length],
  );
  const removeAttachment = React.useCallback((id: number) => {
    setAttachments((xs) => {
      const gone = xs.find((a) => a.id === id);
      if (gone) URL.revokeObjectURL(gone.preview);
      return xs.filter((a) => a.id !== id);
    });
  }, []);
  const artifacts = React.useMemo(() => job.data?.artifacts ?? {}, [job.data?.artifacts]);
  const photoViews = React.useMemo(
    () => imagesByView((job.data?.events ?? []).filter((e): e is ArtifactEvent => e.t === "artifact"), artifacts),
    [job.data?.events, artifacts],
  );
  const modelUrl = artifacts.view;
  // Phones load 3D on tap: until then they see a shaded picture of the same model (when this API draws one).
  const caps = useCapabilities();
  const modelPoster = modelUrl && artifacts.stl && caps.has("get", "/jobs/{job_id}/model.png") ? apiUrl(`/jobs/${encodeURIComponent(jobId)}/model.png`) : null;

  const decide = useMutation({
    mutationFn: (body: DecisionBody) => review.decide(cur!.job_id, body),
    onSuccess: (res, body) => {
      qc.setQueryData(["review", "detail", jobId], res.state);
      if (body.action === "improve") toast(`Round ${(cur?.round ?? 1) + 1} started`, { description: res.child_job ? `Job ${res.child_job}` : undefined, tone: "info" });
      else if (body.action === "accept") toast("Accepted", { description: res.part_slug ? `Published as ${res.part_slug}` : "Your sign-off is saved.", tone: "ok" });
      else toast("Rejected", { tone: "info" });
      setPins([]);
      setAttachments((xs) => {
        for (const a of xs) URL.revokeObjectURL(a.preview);
        return [];
      });
      setNote("");
      setWhy("");
      setReason("");
      setHint(null);
      setAcceptOpen(false);
      setRejectOpen(false);
      void qc.invalidateQueries({ queryKey: ["review"] });
    },
    onError: (e) => toast("The decision was not saved", { description: e instanceof Error ? e.message : String(e), tone: "bad" }),
  });

  const improve = React.useCallback(() => {
    const missing = blocker("improve", { pins, note, reason, attachments: keys });
    if (missing) {
      setHint(missing);
      noteRef.current?.focus();
      return;
    }
    decide.mutate(decisionBody("improve", { pins, note, reason, attachments: keys, why }));
  }, [pins, note, reason, keys, why, decide]);

  const onKey = React.useRef<(e: KeyboardEvent) => void>(() => {});
  React.useEffect(() => {
    onKey.current = (e) => {
      if (ignoreKey(e) || !canAct || decide.isPending) return;
      const k = e.key.toLowerCase();
      if (k === "a") setAcceptOpen(true);
      else if (k === "i") improve();
      else if (k === "r") setRejectOpen(true);
      else if (k === "escape" && hint) setHint(null);
      else return;
      e.preventDefault();
    };
  });
  React.useEffect(() => {
    const h = (e: KeyboardEvent) => onKey.current(e);
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  if (detail.isError) return <ErrorState error={detail.error} what="this review" onRetry={() => void detail.refetch()} />;
  if (!d) return <Skeleton className="h-[520px]" />;

  return (
    <div className="space-y-4">
      <div className="space-y-3 rounded-lg border border-border bg-surface p-4">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={STATUS_TONE[status] ?? "neutral"}>{STATUS_TEXT[status] ?? status}</Badge>
          <Badge tone="outline">{roundLabel(cur?.round ?? item?.round ?? 1)}</Badge>
          {isReplay ? <OriginBadge origin="replay" /> : null}
        </div>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <h2 className="text-[18px] leading-tight font-semibold tracking-tight">{title}</h2>
          {Object.keys(artifacts).length ? <ExportMenu artifacts={artifacts} verification={job.data?.verification ?? null} /> : null}
        </div>
        <RoundStrip rounds={d.rounds} />
        <dl className="flex flex-wrap gap-x-6 gap-y-2">
          <div className="space-y-0.5">
            <dt className="text-[11px] text-subtle">Code verdict</dt>
            <dd>
              <Badge tone={verdictTone(verdict)} className="font-mono tnum">
                {verdictText(verdict)}
              </Badge>
            </dd>
          </div>
          <div className="space-y-0.5">
            <dt className="text-[11px] text-subtle">Judge</dt>
            <dd className="font-mono text-[12px]">{scorecardSummary(judge)}</dd>
          </div>
          <div className="space-y-0.5">
            <dt className="text-[11px] text-subtle">Cost</dt>
            <dd className="font-mono text-[12px] tnum">{fmtUsd(item?.cost_usd ?? job.data?.summary.cost_usd)}</dd>
          </div>
        </dl>
        {status === "improving" ? (
          <p role="note" className="rounded-md border border-border bg-surface-2 px-3 py-2 text-[13px]">
            The next round is running
            {cur?.child_job ? (
              <>
                {" "}as{" "}
                <Link href={`/jobs/${encodeURIComponent(cur.child_job)}`} className="font-mono text-accent-text hover:underline">
                  {cur.child_job}
                </Link>
              </>
            ) : null}
            . It comes back here when it finishes.
          </p>
        ) : status === "accepted" ? (
          <p role="note" className="rounded-md border border-ok-border bg-ok-soft px-3 py-2 text-[13px]">
            {cur?.by === "test" ? "Accepted in a test review (not a person)" : "Accepted by a person"}
            {cur?.at ? ` ${timeAgo(cur.at)}` : ""}. The code&apos;s verdict above is unchanged.
          </p>
        ) : status === "rejected" ? (
          <p role="note" className="rounded-md border border-border bg-surface-2 px-3 py-2 text-[13px]">
            Rejected{cur?.reason ? `: “${cur.reason}”` : "."}
          </p>
        ) : null}
      </div>

      {/* the question a reviewer answers: does what was made match what it should be? */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <section aria-label="Should look like" className="min-w-0 space-y-2">
          <h3 className="text-[13px] font-semibold">
            Should look like <span className="font-normal text-muted">· the photo{canAct ? ", click where something is wrong" : ""}</span>
          </h3>
          <PinPhoto
            rectified={d.images.rectified}
            overlay={d.images.overlay}
            focus={d.images.focus}
            pins={pins}
            onChange={canAct ? setPins : undefined}
            earlier={earlier}
            title="Photo"
            worst={d.images.worst}
          />
          {earlier.length ? <p className="text-[12px] text-subtle">Grey pins are from earlier rounds, with the gap there before → after that round (mm, measured by code).</p> : null}
        </section>
        <section aria-label="Agent made" className="min-w-0 space-y-2">
          <h3 className="text-[13px] font-semibold">
            Agent made <span className="font-normal text-muted">· the 3D model, drag to turn it</span>
          </h3>
          <div className="overflow-hidden rounded-lg border border-border bg-surface">
            <CadViewer viewUrl={modelUrl} poster={modelPoster} className="h-[380px] lg:h-[460px]" label="Model" emptyText="This round has no 3D model." />
          </div>
        </section>
      </div>

      {canAct ? (
        <DecisionBar
          pins={pins.length}
          note={note}
          onNote={(v) => {
            setNote(v);
            setHint(null);
          }}
          why={why}
          onWhy={setWhy}
          noteRef={noteRef}
          attachments={attachments}
          onAddImages={addImages}
          onRemoveAttachment={removeAttachment}
          onAccept={() => setAcceptOpen(true)}
          onImprove={improve}
          onReject={() => setRejectOpen(true)}
          pending={decide.isPending ? (decide.variables?.action ?? null) : null}
          hint={hint}
          nextRound={(cur?.round ?? 1) + 1}
          verified={verdict?.status === "verified"}
        />
      ) : null}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <MeasureCheck verification={job.data?.verification} />
        <JudgeScorecard judge={judge} />
      </div>

      <details className="group rounded-lg border border-border bg-surface">
        <summary className="cursor-pointer list-none px-4 py-3 text-[13px] font-medium select-none">
          <span className="text-muted group-open:hidden">▸</span>
          <span className="hidden text-muted group-open:inline">▾</span> More views: slide between photo and model, colour the differences
        </summary>
        <div className="border-t border-border">
          <PhotoPanel views={photoViews} className="h-[420px]" />
        </div>
      </details>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <RoundHistory rounds={d.rounds} />
        <AgentsCard jobId={jobId} costUsd={item?.cost_usd} />
      </div>



      {cur ? (
        <>
          <AcceptDialog
            open={acceptOpen}
            onOpenChange={setAcceptOpen}
            jobId={cur.job_id}
            family={family}
            isReplay={isReplay}
            verdict={verdict}
            pending={decide.isPending}
            onConfirm={(rules, publish) => decide.mutate(decisionBody("accept", { pins, note, reason, rules, publish, why }))}
          />
          <RejectDialog
            open={rejectOpen}
            onOpenChange={setRejectOpen}
            reason={reason}
            setReason={setReason}
            pending={decide.isPending}
            onConfirm={() => decide.mutate(decisionBody("reject", { pins, note, reason, why }))}
          />
        </>
      ) : null}
    </div>
  );
}

type QueueFilter = { family: string; status: string; by: string };
const NO_FILTER: QueueFilter = { family: "", status: "", by: "" };

/** Whether this API's `GET /review/queue` takes the filter parameters (read from its OpenAPI document). */
function useQueueFilterSupport(): boolean {
  const qc = useQueryClient();
  const caps = useCapabilities();
  if (!caps.ready) return false;
  const doc = qc.getQueryData<{ paths?: Record<string, { get?: { parameters?: { name?: string }[] } }> }>(["openapi"]);
  return !!doc?.paths?.[`/api/v1${REVIEW.queue}`]?.get?.parameters?.some((p) => p.name === "family");
}

function QueueFilters({ value, onChange, families, withBy }: { value: QueueFilter; onChange: (f: QueueFilter) => void; families: string[]; withBy: boolean }) {
  const cls = "h-8 w-full rounded-md border border-border-strong bg-surface px-2 text-[12.5px] text-fg";
  return (
    <div className={`grid gap-2 ${withBy ? "grid-cols-3" : "grid-cols-2"}`} role="group" aria-label="Filter the queue">
      <label className="min-w-0 space-y-0.5 text-[11.5px] text-muted">
        <span className="block">Kind</span>
        <select className={cls} value={value.family} onChange={(e) => onChange({ ...value, family: e.target.value })}>
          <option value="">All</option>
          {families.map((f) => (
            <option key={f} value={f}>
              {titleCase(f)}
            </option>
          ))}
        </select>
      </label>
      <label className="min-w-0 space-y-0.5 text-[11.5px] text-muted">
        <span className="block">Status</span>
        <select className={cls} value={value.status} onChange={(e) => onChange({ ...value, status: e.target.value })}>
          <option value="">All</option>
          <option value="waiting">Waiting</option>
          <option value="improving">Being fixed</option>
          <option value="accepted">Accepted</option>
          <option value="rejected">Rejected</option>
        </select>
      </label>
      {withBy ? (
        <label className="min-w-0 space-y-0.5 text-[11.5px] text-muted">
          <span className="block">Decided by</span>
          <select className={cls} value={value.by} onChange={(e) => onChange({ ...value, by: e.target.value })}>
            <option value="">Anyone</option>
            <option value="person">A person</option>
            <option value="test">A test</option>
          </select>
        </label>
      ) : null}
    </div>
  );
}

export function ReviewClient() {
  const caps = useCapabilities();
  const { admin } = useAdmin();
  const router = useRouter();
  const pathname = usePathname();
  const wanted = useSearchParams().get("job");
  const available = caps.has("get", REVIEW.queue);
  const [filter, setFilter] = React.useState<QueueFilter>(NO_FILTER);
  const serverFilters = useQueueFilterSupport();
  const sent = serverFilters ? filter : NO_FILTER;
  const queue = useQuery({
    queryKey: ["review", "queue", sent],
    queryFn: () =>
      serverFilters && (sent.family || sent.status || sent.by)
        ? request(ReviewQueueSchema, REVIEW.queue, { query: { include_replays: 1, family: sent.family || undefined, status: sent.status || undefined, by: sent.by || undefined } })
        : review.queue(true),
    enabled: available,
    refetchInterval: (q) => (q.state.data?.items.some((i) => i.status === "improving") ? 5000 : false),
  });
  const [families, setFamilies] = React.useState<string[]>([]);
  React.useEffect(() => {
    const seen = (queue.data?.items ?? []).map((i) => i.family).filter((f): f is string => !!f);
    if (seen.length) setFamilies((prev) => [...new Set([...prev, ...seen])].sort());
  }, [queue.data]);
  // An older API ignores the filter parameters: family and status are then applied here (both are in every item).
  const items = React.useMemo(
    () => sortQueue((queue.data?.items ?? []).filter((i) => (!filter.family || i.family === filter.family) && (!filter.status || i.status === filter.status))),
    [queue.data, filter.family, filter.status],
  );
  const [selId, setSelId] = React.useState<string | null>(wanted);
  const selItem = selId ? (items.find((i) => i.job_id === selId) ?? items.find((i) => i.root_job === selId)) : items[0];
  const currentId = selItem?.job_id ?? selId ?? null;

  const select = React.useCallback(
    (id: string) => {
      setSelId(id);
      router.replace(`${pathname}?job=${encodeURIComponent(id)}`, { scroll: false });
      if (window.matchMedia("(max-width: 1023px)").matches) document.getElementById("review-detail")?.scrollIntoView({ block: "start" });
    },
    [router, pathname],
  );

  const onKey = React.useRef<(e: KeyboardEvent) => void>(() => {});
  React.useEffect(() => {
    onKey.current = (e) => {
      if (ignoreKey(e) || !items.length) return;
      const k = e.key.toLowerCase();
      if (k !== "j" && k !== "k") return;
      e.preventDefault();
      const i = Math.max(0, items.findIndex((x) => x.job_id === currentId));
      const next = items[k === "j" ? Math.min(items.length - 1, i + 1) : Math.max(0, i - 1)];
      if (next && next.job_id !== currentId) select(next.job_id);
    };
  });
  React.useEffect(() => {
    const h = (e: KeyboardEvent) => onKey.current(e);
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);

  return (
    <>
      <PageHeader
        compact
        eyebrow="Review"
        title="Review finished parts"
        description="Compare the photo with what the agent made, then accept, send back with pins, or reject. The measurements decide pass or fail; your decision is a separate sign-off."
        actions={
          <Link href="/review/log" className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-surface px-3 text-[13px] font-medium hover:bg-surface-2">
            <History className="size-4" aria-hidden /> Feedback log
          </Link>
        }
      />
      <Container className="space-y-6 py-8">
        {!caps.ready ? (
          <Skeleton className="h-40" />
        ) : !available ? (
          <EmptyState icon={ClipboardCheck} title="Review is not available on this server yet">
            This API does not serve a review queue. Nothing is shown rather than an example.
          </EmptyState>
        ) : (
          <>
            {!admin ? <AdminAccess what="Accepting, sending back or rejecting a part needs an admin token. Everyone can see the queue, the scorecards and the history." /> : null}
            <StatsStrip />
            {queue.isPending ? (
              <Skeleton className="h-64" />
            ) : queue.isError ? (
              <ErrorState error={queue.error} what="the review queue" onRetry={() => void queue.refetch()} />
            ) : !items.length && !selId && filter === NO_FILTER ? (
              <EmptyState icon={ClipboardCheck} title="Nothing to review">
                Finished fix jobs appear here.
              </EmptyState>
            ) : (
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
                <div className="min-w-0 space-y-2 lg:sticky lg:top-24 lg:self-start">
                  <QueueFilters value={filter} onChange={setFilter} families={families} withBy={serverFilters} />
                  {items.length ? <QueueList items={items} selected={currentId} onSelect={select} /> : <EmptyState compact title="Nothing in the queue" />}
                  <AdminLock />
                </div>
                <div id="review-detail" className="min-w-0 scroll-mt-20">
                  {currentId ? <ReviewDetailPanel key={currentId} jobId={currentId} item={selItem} admin={admin} /> : null}
                </div>
              </div>
            )}
          </>
        )}
      </Container>
    </>
  );
}
