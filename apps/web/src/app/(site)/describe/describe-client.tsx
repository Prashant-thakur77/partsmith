"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Camera, CheckCircle2, CircleAlert, CircleSlash, MessageSquareText, RotateCcw, Sparkles } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { Container, PageHeader } from "@/components/layout/page";
import { PrintItPanel } from "@/components/product/print-it-panel";
import { TemplateAckNotice, TemplateExport } from "@/components/product/template-export";
import { useTemplateBake } from "@/components/product/use-template-bake";
import { KnobPanel } from "@/components/registry/knob-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input, Label, Textarea } from "@/components/ui/input";
import { ModeBadge } from "@/components/ui/provenance";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Tooltip } from "@/components/ui/tooltip";
import { CadViewer } from "@/components/viewer/cad-viewer";
import { TranscribeButton } from "@/components/voice-button";
import { artifactUrl } from "@/lib/api";
import { PRODUCT, productApi, type CheckItem, type DescribeRecord } from "@/lib/api-product";
import { useCapabilities } from "@/lib/capabilities";
import { FAMILIES } from "@/lib/families";
import { fmtNum } from "@/lib/format";
import { changedValues, parseAnswers, valueTag, type ValueTag } from "@/lib/playground";
import { cn } from "@/lib/utils";

const EXAMPLES = [
  "A cable clip for a 6 mm cable, screws down with one M3 screw, 20 mm wide",
  "A spacer 12 mm tall for an M3 screw, outer diameter 7 mm",
  "A knob for a 6 mm D-shaft, 35 mm diameter",
  "An L-bracket 60 mm long for M4 screws, 3 mm thick",
];

const TAG_TONE: Record<ValueTag, "ok" | "info" | "neutral" | "accent" | "warn"> = {
  "you said": "ok",
  "you answered": "ok",
  default: "neutral",
  inferred: "accent",
  changed: "warn",
};

function DescribeForm({ initial = "" }: { initial?: string }) {
  const qc = useQueryClient();
  const router = useRouter();
  const pathname = usePathname();
  const [text, setText] = React.useState(initial);
  const id = React.useId();
  const run = useMutation({
    mutationFn: (t: string) => productApi.describe(t),
    onSuccess: (rec) => {
      qc.setQueryData(["describe", rec.id], rec);
      router.push(`${pathname}?id=${encodeURIComponent(rec.id)}`, { scroll: false });
    },
  });
  const ok = text.trim().length >= 3;
  return (
    <form
      className="space-y-3 rounded-xl border border-border bg-surface p-4 sm:p-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (ok) run.mutate(text.trim());
      }}
    >
      <div className="flex flex-wrap items-end justify-between gap-2">
        <Label htmlFor={id} className="text-[14px] font-semibold">
          What do you need? Say the numbers you know.
        </Label>
        <TranscribeButton onText={(t) => setText((cur) => (cur.trim() ? `${cur.trim()} ${t}` : t))} label="Say it" />
      </div>
      <Textarea id={id} value={text} onChange={(e) => setText(e.target.value)} maxLength={600} rows={3} placeholder={EXAMPLES[0]} aria-describedby={`${id}-hint`} />
      <p id={`${id}-hint`} className="text-[12px] text-subtle">
        Millimetres, screw sizes (M3, M4) and counts work best. Nothing is made up: every number you give is checked against the built model.
      </p>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[12px] text-subtle">Try:</span>
        {EXAMPLES.map((ex) => (
          <button key={ex} type="button" onClick={() => setText(ex)} className="rounded-full border border-border px-2.5 py-0.5 text-left text-[12px] text-muted transition-colors hover:border-border-strong hover:text-fg">
            {ex}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" variant="primary" disabled={!ok || run.isPending}>
          {run.isPending ? <Spinner className="text-accent-fg" label="Working" /> : <Sparkles aria-hidden />}
          {run.isPending ? "Picking a program and building it…" : "Make it"}
        </Button>
        <span className="text-[12px] text-muted">
          or{" "}
          <Link href="/playground" className="font-medium text-accent-text hover:underline">
            start from an example
          </Link>
        </span>
      </div>
      {run.isError ? <ErrorState error={run.error} compact what="your description" /> : null}
    </form>
  );
}

function Questions({ rec }: { rec: DescribeRecord }) {
  const qc = useQueryClient();
  const [fields, setFields] = React.useState<Record<string, string>>(() => Object.fromEntries(rec.questions.map((q) => [q.param, ""])));
  const [bad, setBad] = React.useState<string[]>([]);
  const send = useMutation({
    mutationFn: (answers: Record<string, number | null>) => productApi.describeAnswer(rec.id, answers),
    onSuccess: (r) => qc.setQueryData(["describe", rec.id], r),
  });
  const submit = (useDefaults: boolean) => {
    const parsed = parseAnswers(useDefaults ? Object.fromEntries(rec.questions.map((q) => [q.param, ""])) : fields);
    setBad(parsed.bad);
    if (!parsed.bad.length) send.mutate(parsed.answers);
  };
  const said = rec.values.filter((v) => v.source === "user");
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h2" className="flex items-center gap-2 text-[15px]">
          <MessageSquareText className="size-4 text-muted" aria-hidden /> A few numbers are missing
        </CardTitle>
        <p className="text-[13px] text-muted">
          This looks like a <span className="font-medium text-fg">{rec.title || rec.template}</span>
          {said.length ? <> — you gave {said.map((v) => `“${v.quote}”`).join(", ")}</> : null}. These sizes decide whether it fits; answer what you know.
        </p>
      </CardHeader>
      <CardContent>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            submit(false);
          }}
        >
          <div className="grid gap-4 sm:grid-cols-2">
            {rec.questions.map((q) => (
              <div key={q.param} className="space-y-1.5">
                <Label htmlFor={`q-${q.param}`} className="text-[13px]">
                  {q.label}
                  {q.unit ? <span className="text-muted"> ({q.unit})</span> : null}
                </Label>
                <Input
                  id={`q-${q.param}`}
                  inputMode="decimal"
                  value={fields[q.param] ?? ""}
                  onChange={(e) => setFields((f) => ({ ...f, [q.param]: e.target.value }))}
                  placeholder={`default ${fmtNum(q.default, q.step < 1 ? 2 : 0)}`}
                  aria-invalid={bad.includes(q.param) || undefined}
                  aria-describedby={`q-${q.param}-hint`}
                />
                <p id={`q-${q.param}-hint`} className={cn("text-[11.5px]", bad.includes(q.param) ? "text-bad" : "text-subtle")}>
                  {bad.includes(q.param) ? "Type a number, or leave it empty." : `${fmtNum(q.min, 2)}–${fmtNum(q.max, 2)} ${q.unit}. Empty keeps the default.`}
                </p>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" disabled={send.isPending}>
              {send.isPending ? <Spinner className="text-accent-fg" label="Building" /> : <ArrowRight aria-hidden />} Build it
            </Button>
            <Button type="button" variant="outline" disabled={send.isPending} onClick={() => submit(true)}>
              Use the defaults
            </Button>
          </div>
          {send.isError ? <ErrorState error={send.error} compact what="your answers" /> : null}
        </form>
      </CardContent>
    </Card>
  );
}

function CheckIcon({ status }: { status: CheckItem["status"] }) {
  if (status === "met") return <CheckCircle2 className="size-4 text-ok" aria-label="met" />;
  if (status === "knob_only") return <CircleSlash className="size-4 text-subtle" aria-label="set on the knob, not measured" />;
  return <CircleAlert className="size-4 text-warn" aria-label={status === "clamped" ? "outside the knob's range" : "not met"} />;
}

function ChecksCard({ rec }: { rec: DescribeRecord }) {
  const c = rec.checks;
  if (!c) return null;
  return (
    <section aria-labelledby="checks-title" className="space-y-3 rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="checks-title" className="text-[15px] font-semibold tracking-tight">
          Your numbers vs the built model
        </h2>
        <Badge tone={c.status === "matches" ? "ok" : c.status === "partial" ? "warn" : "neutral"}>{c.label}</Badge>
      </div>
      {c.items.length ? (
        <div className="scrollbar-thin overflow-x-auto">
          <table className="w-full text-[12.5px]">
            <thead>
              <tr className="border-b border-border text-left text-[11px] tracking-wide text-subtle uppercase">
                <th scope="col" className="py-1.5 pr-3 font-medium">You said</th>
                <th scope="col" className="hidden py-1.5 pr-3 font-medium sm:table-cell">Knob</th>
                <th scope="col" className="py-1.5 pr-3 text-right font-medium">Set to</th>
                <th scope="col" className="py-1.5 pr-3 text-right font-medium">Measured</th>
                <th scope="col" className="py-1.5 font-medium"><span className="sr-only">Result</span></th>
              </tr>
            </thead>
            <tbody>
              {c.items.map((i) => (
                <tr key={i.param} className="border-b border-border align-top last:border-0">
                  <td className="py-2 pr-3">“{i.quote}”</td>
                  <td className="hidden py-2 pr-3 text-muted sm:table-cell">{i.label || i.param}</td>
                  <td className="py-2 pr-3 text-right font-mono whitespace-nowrap tnum">
                    {fmtNum(i.set, 2)} {i.unit}
                  </td>
                  <td className="py-2 pr-3 text-right font-mono whitespace-nowrap tnum">
                    {i.measured != null ? (
                      <Tooltip content={i.method}>
                        <span tabIndex={0} className="cursor-help underline decoration-dotted underline-offset-2">
                          {fmtNum(i.measured, 2)} {i.unit}
                        </span>
                      </Tooltip>
                    ) : (
                      <span className="text-subtle">—</span>
                    )}
                  </td>
                  <td className="py-2">
                    <CheckIcon status={i.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {c.items.filter((i) => i.note).map((i) => (
        <p key={i.param} className="text-[12px] text-muted">
          <span className="font-medium text-fg">{i.label || i.param}:</span> {i.note}
        </p>
      ))}
      <p className="text-[11.5px] text-subtle">
        Tolerance {c.tolerance}. {c.note}
      </p>
    </section>
  );
}

function Result({ rec }: { rec: DescribeRecord }) {
  const params = rec.params;
  const baked = rec.bake?.params ?? {};
  const [values, setValues] = React.useState<Record<string, number>>(baked);
  const [ack, setAck] = React.useState(false);
  const moved = params.some((p) => Math.abs((values[p.name] ?? p.default) - (baked[p.name] ?? p.default)) > p.step / 2);
  const live = useTemplateBake(rec.template, moved ? values : null);
  const viewUrl = moved ? (live.data?.artifacts.view ?? rec.bake?.view_url) : rec.bake?.view_url;
  const plan = moved ? live.data?.print_plan : rec.print_plan;
  const name = rec.template!;
  const tags = Object.fromEntries(
    rec.values.map((v) => {
      const p = params.find((x) => x.name === v.param);
      const tag = valueTag(v, values[v.param], p?.step ?? 0);
      const tip = tag === "changed" ? "You moved this knob after the checks ran." : v.quote ? `“${v.quote}”${v.note ? ` — ${v.note}` : ""}` : v.note || (tag === "default" ? "The template's default value." : "");
      return [
        v.param,
        <span key={v.param} className="inline-flex max-w-full items-center gap-1.5">
          <Badge tone={TAG_TONE[tag]}>{tag}</Badge>
          {tip ? <span className="truncate" title={tip}>{tip}</span> : null}
        </span>,
      ];
    }),
  );
  const fam = rec.family && (FAMILIES as readonly string[]).includes(rec.family) ? rec.family : "";
  const fixHref = `/fix?${new URLSearchParams({ ...(fam ? { family: fam } : {}), intent: `${rec.title || "Part"} I described: ${rec.text}`.slice(0, 480) })}`;
  const reason = live.data?.ship?.reason ?? rec.ship?.reason ?? "";
  const said = rec.values.filter((v) => v.source === "user" || v.source === "answer").length;

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div className="space-y-2">
          <h2 className="text-[22px] leading-tight font-semibold tracking-[-0.02em]">{rec.title || rec.template}</h2>
          <div className="flex flex-wrap items-center gap-1.5">
            {rec.checks ? <Badge tone={rec.checks.status === "matches" ? "ok" : rec.checks.status === "partial" ? "warn" : "neutral"}>{rec.checks.label}</Badge> : null}
            <Badge tone="outline">not verified: no photo</Badge>
            {rec.planner ? <ModeBadge mode={rec.planner.mode} hideLive /> : null}
            <Badge tone="neutral" className="font-mono">
              {name}.py · {said} of {rec.values.length} values from you
            </Badge>
          </div>
          <p className="max-w-2xl text-[13px] text-muted">“{rec.text}”</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="primary" size="sm" className="h-auto min-h-8 shrink py-1.5 whitespace-normal">
            <Link href={fixHref}>
              <Camera aria-hidden /> Add a photo to verify it against the real part
            </Link>
          </Button>
          <Button asChild variant="outline" size="sm" className="h-auto min-h-8 shrink py-1.5 whitespace-normal">
            <Link href={`/playground?t=${encodeURIComponent(name)}&${new URLSearchParams(Object.entries(changedValues(params, values)).map(([k, v]) => [k, String(v)]))}`}>Open in the playground</Link>
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-6">
          <div className="overflow-hidden rounded-xl border border-border bg-surface">
            <CadViewer viewUrl={artifactUrl(viewUrl)} busy={moved && live.pending} className="h-[340px] sm:h-[440px]" label={`3D model of ${rec.title || name}`} />
          </div>
          <ChecksCard rec={rec} />
          {rec.plan_notes.length ? (
            <details className="text-[12px] text-muted">
              <summary className="cursor-pointer select-none">What code changed in the plan ({rec.plan_notes.length})</summary>
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                {rec.plan_notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
        <div className="space-y-5">
          <Card>
            <CardContent className="pt-4">
              <KnobPanel params={params} values={values} onChange={setValues} bake={moved ? live.data : null} pending={moved && live.pending} error={live.error} tags={tags} />
              {moved ? <p className="mt-3 text-[12px] text-warn">You changed knobs after the checks: the table on the left is for the values you described.</p> : null}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle as="h2">Export</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {reason ? <TemplateAckNotice ack={ack} onAck={setAck} reason={reason} /> : null}
              <TemplateExport template={name} values={values} ack={ack && !!reason} />
            </CardContent>
          </Card>
          <PrintItPanel
            plan={plan}
            title={rec.title || name}
            stlUrl={productApi.templateDownloadUrl(name, values, "stl")}
            threemfUrl={productApi.templateDownloadUrl(name, values, "3mf")}
            couponUrl={rec.coupon ? productApi.templateCouponUrl(name, values) : null}
            family={rec.family}
            disabled={!ack || !reason}
            note={!ack ? "Tick the box above to unlock the files." : null}
          />
        </div>
      </div>
    </div>
  );
}

function NoFit({ rec }: { rec: DescribeRecord }) {
  return (
    <EmptyState icon={CircleSlash} title="No part program fits this description">
      <div className="space-y-3 text-left">
        <p>{rec.no_fit?.reason}. PartSmith only makes parts here from its family programs, and it will not free-write CAD from a description.</p>
        {rec.no_fit?.templates.length ? <p className="text-[12.5px] text-subtle">Programs it has: {rec.no_fit.templates.join(", ")}.</p> : null}
        <div className="flex flex-wrap justify-center gap-2">
          {(rec.no_fit?.next ?? []).map((n) => (
            <Button key={n.href} asChild variant={n.href === "/fix" ? "primary" : "outline"} size="sm">
              <Link href={n.href}>{n.label}</Link>
            </Button>
          ))}
        </div>
      </div>
    </EmptyState>
  );
}

export function DescribeClient() {
  const caps = useCapabilities();
  const sp = useSearchParams();
  const router = useRouter();
  const id = sp.get("id");
  const rec = useQuery({ queryKey: ["describe", id], queryFn: () => productApi.describeGet(id!), enabled: !!id, staleTime: 60_000 });

  if (caps.ready && !caps.has("post", PRODUCT.describe)) {
    return (
      <>
        <PageHeader eyebrow="Describe a part" title="Describe it, with your numbers" />
        <Container className="py-12">
          <EmptyState icon={Sparkles} title="Describe it is not on this server yet">
            This PartSmith API has no describe route. <Link href="/fix" className="text-accent-text hover:underline">Photograph the part</Link> instead.
          </EmptyState>
        </Container>
      </>
    );
  }
  const r = rec.data;
  return (
    <>
      <PageHeader
        eyebrow="Describe a part"
        title="Describe it, with your numbers"
        description="No part in hand? Say what it is and the sizes you know. A model picks one of PartSmith's part programs and sets its knobs; code checks the plan, builds the part in a sandbox and measures every number you gave on the model."
        compact={!!id}
      />
      <Container className="space-y-6 py-8">
        {!id ? <DescribeForm initial={(sp.get("q") ?? "").slice(0, 500)} /> : null}
        {id && rec.isPending ? <Skeleton className="h-96" /> : null}
        {id && rec.isError ? <ErrorState error={rec.error} what="this description" onRetry={() => void rec.refetch()} /> : null}
        {r?.status === "needs_answers" ? <Questions key={r.id} rec={r} /> : null}
        {r?.status === "done" && r.template ? <Result key={r.id} rec={r} /> : null}
        {r?.status === "no_fit" ? <NoFit rec={r} /> : null}
        {r?.status === "failed" ? (
          <div role="alert" className="rounded-lg border border-bad-border bg-bad-soft px-4 py-3 text-[13px]">
            <p className="font-medium text-fg">The part could not be built</p>
            <p className="text-muted">{r.error}</p>
          </div>
        ) : null}
        {id && r ? (
          <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
            <Button variant="outline" size="sm" onClick={() => router.push("/describe")}>
              <RotateCcw aria-hidden /> Describe another part
            </Button>
            <span className="font-mono text-[11.5px] text-subtle">{r.id}</span>
          </div>
        ) : null}
      </Container>
    </>
  );
}
