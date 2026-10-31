"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Archive, Info, Box, ChevronRight, Download, FileCode2, FileJson, FileText, Layers, Lock, Wand2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { Container, Fact, Section } from "@/components/layout/page";
import { OpenInSlicer } from "@/components/open-in-slicer";
import { PassportShare } from "@/components/passport/passport-share";
import { ArView } from "@/components/registry/ar-view";
import { KnobPanel } from "@/components/registry/knob-panel";
import { useLivePart } from "@/components/registry/live-part";
import { PartDetails } from "./part-details";
import dynamic from "next/dynamic";
import { useCapabilities } from "@/lib/capabilities";
import { shipState } from "@/lib/ship";

// Below the first screen on phones and only useful after interaction: loaded after hydration.
const ExportGateNotice = dynamic(() => import("@/components/export-gate").then((m) => m.ExportGateNotice), { ssr: false });
const FitPresets = dynamic(() => import("@/components/jobs/fit-presets").then((m) => m.FitPresets), { ssr: false });
const CouponFit = dynamic(() => import("@/components/jobs/coupon-fit").then((m) => m.CouponFit), { ssr: false });
import { ShareButtons } from "@/components/registry/share-buttons";
import { PartBuyOrPrintCard } from "@/components/jobs/buy-or-print-card";
import { VariantMaker } from "@/components/product/variant-maker";
import { LoadNoteBox } from "@/components/product/load-note";
import { UncheckedList } from "@/components/jobs/evidence-notes";
import { PartStatusBadge } from "@/components/registry/part-status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CodeBlock } from "@/components/ui/code-block";
import { ErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { ModeBadge, OriginBadge } from "@/components/ui/provenance";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { toast } from "@/components/ui/toast";
import { Tooltip } from "@/components/ui/tooltip";
import { VerifiedBadge } from "@/components/ui/verified-badge";
import { CadViewer } from "@/components/viewer/cad-viewer";
import { api, artifactUrl } from "@/lib/api";
import type { PartFacts, PartRecord } from "@/lib/api-types";
import { couponFeatures, noteCouponDownload } from "@/lib/coupon-fit";
import { fmtDate, fmtNum, fmtPct, shortSha, titleCase } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import { agentPrompt, curlSnippet, dataSnippet, mcpCallSnippet, pythonSnippet } from "@/lib/snippets";
import { EXTRAS, extrasApi } from "@/lib/api-extras";
import { FORMAT_EXT, downloadName } from "@/lib/download-name";
import { useOrigin } from "@/lib/use-origin";

function useInitialParams(): Record<string, number> {
  const sp = useSearchParams();
  return React.useMemo(() => {
    const out: Record<string, number> = {};
    sp.forEach((v, k) => {
      const n = Number(v);
      if (v !== "" && Number.isFinite(n)) out[k] = n;
    });
    return out;
  }, [sp]);
}

function NoteLabel({ label, note }: { label: string; note?: string }) {
  if (!note) return <>{label}</>;
  return (
    <span className="inline-flex items-center gap-1">
      {label}
      <Tooltip content={note}>
        <span tabIndex={0} role="img" aria-label={`How ${label.toLowerCase()} is computed`} className="inline-flex cursor-help text-subtle hover:text-fg">
          <Info className="size-3.5" aria-hidden />
        </span>
      </Tooltip>
    </span>
  );
}

function FactsList({ facts, notes }: { facts: PartFacts; notes: Record<string, string> }) {
  const [x, y, z] = facts.bbox_mm;
  const gdp = facts.mass_g_pla < 10 ? 2 : 1;
  return (
    <dl>
      <Fact label="Bounding box">
        <span className="font-mono tnum">
          {fmtNum(x, 1)} × {fmtNum(y, 1)} × {fmtNum(z, 1)} <span className="text-muted">mm</span>
        </span>
      </Fact>
      <Fact label={<NoteLabel label="Volume" note={notes.volume_mm3 ?? notes.volume} />}>
        <span className="font-mono tnum">
          {fmtNum(facts.volume_mm3, 0)} <span className="text-muted">mm³</span>
        </span>
      </Fact>
      <Fact label={<NoteLabel label="Mass (PLA / PETG)" note={notes.mass} />}>
        <span className="font-mono tnum">
          {fmtNum(facts.mass_g_pla, gdp)} / {fmtNum(facts.mass_g_petg, gdp)} <span className="text-muted">g</span>
        </span>
      </Fact>
      <Fact label={<NoteLabel label="Print time (estimate)" note={notes.print_minutes_est} />}>
        <span className="font-mono tnum">
          {facts.print_minutes_est < 10 ? fmtNum(facts.print_minutes_est, 1) : Math.round(facts.print_minutes_est)} <span className="text-muted">min</span>
        </span>
      </Fact>
      <Fact label={<NoteLabel label="Supports" note={notes.supports_needed} />}>{facts.supports_needed ? "needed" : "not needed"}</Fact>
      <Fact label={<NoteLabel label="Orientation" note={notes.orientation} />}>
        <span className="block max-w-[14rem] text-right">{facts.orientation}</span>
      </Fact>
    </dl>
  );
}

const FIT_CHOICES = [
  { v: "fits", label: "It fits" },
  { v: "tight", label: "Too tight" },
  { v: "loose", label: "Too loose" },
] as const;

/** "Did it fit?" — recorded as lessons evidence for this part. */
function FitFeedback({ slug, reports }: { slug: string; reports: number }) {
  const fb = useMutation({
    mutationFn: (result: (typeof FIT_CHOICES)[number]["v"]) => api.feedback(slug, { result, kind: "print", note: "" }),
    onSuccess: () => toast("Thanks — recorded", { description: "Fit reports feed the lessons the builder learns from.", tone: "ok" }),
  });
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[13px] font-medium text-fg">Printed it? Did it fit?</span>
        {reports ? <span className="text-[12px] text-subtle">{reports} report{reports === 1 ? "" : "s"}</span> : null}
      </div>
      <div className="grid grid-cols-3 gap-1.5">
      {FIT_CHOICES.map((c) => (
        <Button key={c.v} size="sm" className="px-2" variant={fb.variables === c.v && fb.isSuccess ? "solid" : "outline"} disabled={fb.isPending || fb.isSuccess} onClick={() => fb.mutate(c.v)}>
          {c.label}
        </Button>
      ))}
      </div>
      {fb.isError ? <ErrorState error={fb.error} compact what="your report" /> : null}
    </div>
  );
}

function VerificationCard({ part }: { part: PartRecord }) {
  const v = part.verification;
  const tests = v?.tests ?? [];
  const passed = tests.filter((t) => t.passed).length;
  const verUrl = artifactUrl(part.artifacts.verification);
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3">
        <CardTitle>Verification</CardTitle>
        <VerifiedBadge verification={v} size="sm" />
      </CardHeader>
      <CardContent className="space-y-3">
        {v ? (
          <>
            <p className="text-[13px] leading-6 text-muted">
              {v.verified ? "Verified" : v.status === "best_effort" ? "Best effort" : "Failed"} at{" "}
              <span className="font-mono text-fg tnum">{v.max_error_mm != null ? `${fmtNum(v.max_error_mm)} mm` : "—"}</span> max error vs the
              photo (limit <span className="font-mono tnum">{fmtNum(v.thresholds.hausdorff_mm)} mm</span>)
              {tests.length ? (
                <>
                  {" "}· <span className="font-mono text-fg tnum">{passed}/{tests.length}</span> tests passed
                </>
              ) : null}
              {part.created_at ? <> · built {fmtDate(part.created_at)}</> : null}
              {part.provenance.photo_shas[0] ? (
                <>
                  {" "}· photo <span className="font-mono">{shortSha(part.provenance.photo_shas[0])}</span>
                </>
              ) : null}
            </p>
            <div className="flex flex-wrap gap-1.5">
              <OriginBadge origin={v.origin} />
              {v.views.map((m) => (
                <Badge key={m.view} tone="neutral" className="font-mono tnum">
                  {m.view}: IoU {fmtNum(m.iou, 3)}
                </Badge>
              ))}
            </div>
            {v.reasons.length ? (
              <ul className="list-disc space-y-0.5 pl-4 text-[12px] text-muted">
                {v.reasons.slice(0, 4).map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            ) : null}
            {v.unchecked.length ? <UncheckedList items={v.unchecked} as="h4" className="px-3 py-2.5" /> : null}
            {verUrl ? (
              <a href={verUrl} className="inline-flex items-center gap-1 text-[12px] font-medium text-accent-text hover:underline">
                <FileJson className="size-3.5" aria-hidden /> verification.json
              </a>
            ) : null}
          </>
        ) : (
          <p className="text-[13px] text-muted">No verification record. This part has not been checked against a photo.</p>
        )}
      </CardContent>
    </Card>
  );
}

function VariantBox({ slug, onApply }: { slug: string; onApply: (p: Record<string, number>) => void }) {
  const [want, setWant] = React.useState("");
  const v = useMutation({ mutationFn: (w: string) => api.variant(slug, w), onSuccess: (r) => onApply(r.params) });
  return (
    <div className="space-y-2">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (want.trim()) v.mutate(want.trim());
        }}
      >
        <Input value={want} onChange={(e) => setWant(e.target.value)} placeholder="In plain words: 2 mm taller, M4 hole" aria-label="Describe a variant" />
        <Button type="submit" variant="outline" disabled={!want.trim() || v.isPending} aria-label="Apply variant">
          {v.isPending ? <Spinner label="Working" /> : <Wand2 aria-hidden />}
        </Button>
      </form>
      {v.isError ? <ErrorState error={v.error} compact what="the variant" /> : null}
      {v.data ? (
        <div className="space-y-1 text-[12px]" aria-live="polite">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone="neutral" className="font-mono tnum">confidence {fmtPct(v.data.confidence, 0)}</Badge>
            <ModeBadge mode={v.data.mode} hideLive />
          </div>
          {v.data.applied.map((a) => (
            <div key={a} className="flex gap-1.5">
              <Badge tone="ok">applied</Badge> <span className="text-muted">{a}</span>
            </div>
          ))}
          {v.data.not_applied.map((a) => (
            <div key={a} className="flex gap-1.5">
              <Badge tone="warn">not applied</Badge> <span className="text-muted">{a}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** `withDetails`: render provenance, lineage, knob reference and matching here (only when the server could not). */
export function PartClient({ slug, withDetails = true }: { slug: string; withDetails?: boolean }) {
  const [gateAck, setGateAck] = React.useState(false);
  const caps = useCapabilities();
  const router = useRouter();
  const pathname = usePathname();
  const origin = useOrigin();
  const initial = useInitialParams();
  const live = useLivePart(slug, initial);
  const part = live.part.data;
  const matching = useQuery({ queryKey: ["matching", slug], queryFn: () => api.matching(slug), enabled: !!part && withDetails });

  // Keep the URL shareable: changed knobs go into the query string.
  const dv = useDebounced(live.values, 400);
  React.useEffect(() => {
    if (!part) return;
    const qs = new URLSearchParams();
    for (const p of part.params) {
      const v = dv[p.name];
      if (v !== undefined && v !== part.defaults[p.name]) qs.set(p.name, String(v));
    }
    const next = `${pathname}${qs.toString() ? `?${qs}` : ""}`;
    if (next !== `${window.location.pathname}${window.location.search}`) router.replace(next, { scroll: false });
  }, [dv, part, pathname, router]);

  if (live.part.isError) {
    return (
      <Container className="py-16">
        <ErrorState error={live.part.error} what="this part" onRetry={() => void live.part.refetch()} />
      </Container>
    );
  }
  if (!part) {
    return (
      <Container className="space-y-6 py-8">
        <Skeleton className="h-8 w-72" />
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
          <Skeleton className="h-[480px]" />
          <Skeleton className="h-[480px]" />
        </div>
      </Container>
    );
  }

  const values = live.values;
  const ship = shipState(part.verification, part.ship);
  const gate = { locked: ship !== "verified", ack: gateAck, setAck: setGateAck, open: ship === "verified" || (ship === "best_effort" && gateAck) };
  const facts = (live.changed ? live.bake.data?.facts : null) ?? part.facts ?? live.bake.data?.facts ?? null;
  const dl = (format: "stl" | "3mf" | "step" | "py" | "glb") =>
    api.bakeDownloadUrl(slug, values, format, ship === "best_effort" && gateAck);
  const glb = live.changed ? dl("glb") : (artifactUrl(part.artifacts.glb) ?? dl("glb"));
  const fileName = (format: "stl" | "3mf" | "step" | "py") =>
    downloadName(slug, FORMAT_EXT[format] ?? `.${format}`, values, part.defaults, part.params.map((p) => p.name));

  return (
    <>
      <div className="border-b border-border bg-surface/40">
        <Container className="space-y-3 py-6">
          <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-[12px] text-muted">
            <Link href="/parts" className="hover:text-fg">
              Registry
            </Link>
            <ChevronRight className="size-3" aria-hidden />
            <Link href={`/parts?family=${encodeURIComponent(part.family)}`} className="hover:text-fg">
              {titleCase(part.family)}
            </Link>
          </nav>
          {part.withdrawn ? (
            <p role="status" className="rounded-md border border-warn-border bg-warn-soft px-3 py-2 text-[13px]">
              <strong className="font-semibold">Withdrawn from search.</strong> An admin took this part out of the registry: “{part.withdrawn.reason}”.
              The page and files stay up for anyone who already has the link.
            </p>
          ) : null}
          <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div className="space-y-2">
              <h1 className="text-[26px] leading-tight font-semibold tracking-[-0.025em] sm:text-[30px]">{part.title}</h1>
              <div className="flex flex-wrap items-center gap-1.5">
                <PartStatusBadge status={part.status} maxErrorMm={part.verification?.max_error_mm} />
                <OriginBadge origin={part.provenance.origin} />
                <ModeBadge mode={part.provenance.provider_mode} hideLive />
                <Badge tone="outline" className="font-mono">v{part.version}</Badge>
                <Badge tone="outline">{part.licence}</Badge>
                {part.tags.slice(0, 4).map((t) => (
                  <Badge key={t} tone="neutral">
                    {t}
                  </Badge>
                ))}
              </div>
              {part.summary ? <p className="max-w-2xl text-[14px] leading-6 text-muted">{part.summary}</p> : null}
            </div>
            <div className="flex flex-wrap gap-2">
              <ArView glbUrl={glb} title={part.title} />
              <ShareButtons title={part.title} verified={!!part.verification?.verified} />
              {gate.open ? (
                <Button asChild variant="primary" size="sm">
                  <a href={dl("stl")} download={fileName("stl")}>
                    <Download aria-hidden /> Download STL
                  </a>
                </Button>
              ) : (
                <Button asChild variant="outline" size="sm">
                  <a href="#downloads">
                    <Lock aria-hidden /> {ship === "blocked" ? "No download (failed)" : "Download (not verified)"}
                  </a>
                </Button>
              )}
            </div>
          </div>
        </Container>
      </div>

      <Container className="space-y-14 py-8">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
          <div className="overflow-hidden rounded-xl border border-border bg-surface lg:sticky lg:top-20 lg:self-start">
            <CadViewer viewUrl={live.viewUrl} poster={artifactUrl(part.thumbnail_url)} poster2x={artifactUrl(part.thumbnail_2x_url)} busy={live.bake.pending && live.changed} className="h-[380px] sm:h-[520px] lg:h-[min(620px,calc(100dvh-120px))]" label={`3D model of ${part.title}`} />
          </div>
          <div className="space-y-5">
            <Card>
              <CardContent className="pt-4">
                <KnobPanel
                  params={part.params}
                  values={values}
                  onChange={live.setValues}
                  bake={live.bake.data}
                  pending={live.bake.pending && live.changed}
                  error={live.bake.error}
                />
                <FitPresets slug={slug} params={part.params} values={values} onApply={(p) => live.setValues({ ...values, ...p })} />
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Ask for a variant</CardTitle>
              </CardHeader>
              <CardContent>
                <VariantBox slug={slug} onApply={(p) => live.setValues({ ...values, ...p })} />
              </CardContent>
            </Card>
            <Card id="make-variant">
              <CardContent className="pt-4">
                <VariantMaker
                  slug={slug}
                  params={part.params}
                  values={values}
                  base={part.defaults}
                  verified={!!part.verification?.verified}
                  downloadUrl={(f) => (gate.open ? dl(f) : undefined)}
                  lockedNote={ship === "blocked" ? "This part failed its check, so nothing downloads." : "Acknowledge the notice under Downloads first."}
                />
              </CardContent>
            </Card>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <VerificationCard part={part} />
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle>Real-world facts</CardTitle>
              {live.changed && live.bake.data?.facts ? <Badge tone="accent">this variant</Badge> : null}
            </CardHeader>
            <CardContent>{facts ? <FactsList facts={facts} notes={{ ...part.facts_notes, ...(live.bake.data?.facts_notes ?? {}) }} /> : <p className="text-[13px] text-muted">Facts appear after the first bake.</p>}</CardContent>
          </Card>
          <Card id="downloads">
            <CardHeader>
              <CardTitle>Downloads</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1.5">
              {gate.locked ? (
                <ExportGateNotice verification={part.verification} couponUrl={part.artifacts.coupon ? artifactUrl(part.artifacts.coupon) : undefined} ack={gate.ack} onAck={gate.setAck} />
              ) : null}
              <fieldset disabled={!gate.open} className="space-y-1.5 disabled:pointer-events-none disabled:opacity-45" aria-label="Download files">
              {(
                [
                  { f: "stl", label: "STL", sub: "mesh for any slicer", icon: Box },
                  { f: "3mf", label: "3MF", sub: "with print settings", icon: Layers },
                  { f: "step", label: "STEP", sub: "editable B-rep", icon: Box },
                  { f: "py", label: "part.py", sub: "parametric CadQuery source", icon: FileCode2 },
                ] as const
              ).map((d) => (
                <a
                  key={d.f}
                  href={gate.open ? dl(d.f) : undefined}
                  aria-disabled={!gate.open || undefined}
                  tabIndex={gate.open ? undefined : -1}
                  download={fileName(d.f)}
                  className="flex items-center gap-3 rounded-md border border-border px-3 py-2 text-[13px] transition-colors hover:border-border-strong hover:bg-surface-2"
                >
                  <d.icon className="size-4 text-muted" aria-hidden />
                  <span className="flex-1">
                    <span className="font-medium">{d.label}</span> <span className="text-subtle">· {d.sub}</span>
                  </span>
                  <Download className="size-3.5 text-subtle" aria-hidden />
                </a>
              ))}
              {caps.has("get", "/parts/{slug}/bundle.zip") ? (
                <a
                  href={gate.open ? api.bundleZipUrl(slug, values, ship !== "verified") : undefined}
                  aria-disabled={!gate.open || undefined}
                  tabIndex={gate.open ? undefined : -1}
                  download
                  className="flex items-center gap-3 rounded-md border border-border px-3 py-2 text-[13px] transition-colors hover:border-border-strong hover:bg-surface-2"
                >
                  <Archive className="size-4 text-muted" aria-hidden />
                  <span className="flex-1">
                    <span className="font-medium">Everything (.zip)</span> <span className="text-subtle">· files, part.py, README, licence</span>
                  </span>
                  <Download className="size-3.5 text-subtle" aria-hidden />
                </a>
              ) : null}
              <a
                href={api.templatePdfUrl(slug, values)}
                className="flex items-center gap-3 rounded-md border border-border px-3 py-2 text-[13px] transition-colors hover:border-border-strong hover:bg-surface-2"
              >
                <FileText className="size-4 text-muted" aria-hidden />
                <span className="flex-1">
                  <span className="font-medium">1:1 paper template</span> <span className="text-subtle">· PDF</span>
                </span>
                <Download className="size-3.5 text-subtle" aria-hidden />
              </a>
              </fieldset>
              {part.artifacts.coupon && !gate.locked ? (
                <a
                  href={artifactUrl(part.artifacts.coupon)}
                  download
                  onClick={noteCouponDownload}
                  className="flex items-center gap-3 rounded-md border border-border px-3 py-2 text-[13px] transition-colors hover:border-border-strong hover:bg-surface-2"
                >
                  <Box className="size-4 text-muted" aria-hidden />
                  <span className="flex-1">
                    <span className="font-medium">Fit-test coupon</span> <span className="text-subtle">· small test print for the fit</span>
                  </span>
                  <Download className="size-3.5 text-subtle" aria-hidden />
                </a>
              ) : null}
              <OpenInSlicer fileUrl={dl("3mf")} ship={ship} ack={gateAck} className="border-t border-border pt-3" />
              {part.passport ? <PassportShare passport={part.passport} title={part.title} className="border-t border-border pt-3" /> : null}
              <p className="pt-1 text-[11px] text-subtle">Downloads use the knob values above.</p>
              <div className="border-t border-border pt-3">
                <FitFeedback slug={slug} reports={part.fit_reports.length} />
              </div>
              {ship !== "blocked" ? <CouponFit features={couponFeatures(null, part.params)} slug={slug} className="border-t border-border pt-3" /> : null}
            </CardContent>
          </Card>
        </div>

        <LoadNoteBox family={part.family} headingLevel="h2" className="max-w-2xl" />

        <PartBuyOrPrintCard slug={slug} className="max-w-2xl" />

        <Section id="use" title="Use it" description="Same part, same knobs — from Python, a shell, an MCP client or your coding agent.">
          <Tabs defaultValue="python">
            <TabsList>
              <TabsTrigger value="python">Python</TabsTrigger>
              <TabsTrigger value="rest">REST</TabsTrigger>
              <TabsTrigger value="mcp">MCP</TabsTrigger>
              <TabsTrigger value="agent">Agent prompt</TabsTrigger>
              <TabsTrigger value="embed">Embed</TabsTrigger>
              {caps.has("get", EXTRAS.verificationJson) || caps.has("get", EXTRAS.paramsJson) ? <TabsTrigger value="data">Data</TabsTrigger> : null}
            </TabsList>
            <TabsContent value="python">
              <CodeBlock title="python" code={pythonSnippet(slug, values, origin)} />
            </TabsContent>
            <TabsContent value="rest">
              <CodeBlock title="shell" code={curlSnippet(slug, values, origin)} />
            </TabsContent>
            <TabsContent value="mcp">
              <CodeBlock title="MCP tool call" code={mcpCallSnippet(slug, values)} />
            </TabsContent>
            <TabsContent value="agent">
              <CodeBlock title="paste into your agent" wrap code={agentPrompt(slug, part.title, origin)} />
            </TabsContent>
            {caps.has("get", EXTRAS.verificationJson) || caps.has("get", EXTRAS.paramsJson) ? (
              <TabsContent value="data" className="space-y-3">
                <p className="text-[13px] text-muted">The numbers behind this page as plain JSON, straight from the stored record.</p>
                <div className="flex flex-wrap gap-2" aria-label="Part data files">
                  {caps.has("get", EXTRAS.verificationJson) && part.verification ? (
                    <Button asChild variant="outline" size="sm">
                      <a href={extrasApi.verificationJsonUrl(slug)} target="_blank" rel="noopener noreferrer">
                        <FileJson aria-hidden /> verification.json
                      </a>
                    </Button>
                  ) : null}
                  {caps.has("get", EXTRAS.paramsJson) ? (
                    <Button asChild variant="outline" size="sm">
                      <a href={extrasApi.paramsJsonUrl(slug)} target="_blank" rel="noopener noreferrer">
                        <FileJson aria-hidden /> params.json
                      </a>
                    </Button>
                  ) : null}
                </div>
                <CodeBlock title="shell" code={dataSnippet(slug, origin)} />
              </TabsContent>
            ) : null}
            <TabsContent value="embed">
              <CodeBlock
                title="HTML"
                wrap
                code={`<iframe src="${origin}/embed/parts/${slug}" width="640" height="480" title="${part.title} — PartSmith" loading="lazy" style="border:0;border-radius:12px"></iframe>`}
              />
            </TabsContent>
          </Tabs>
        </Section>

        {withDetails ? <PartDetails part={part} matching={matching.isPending ? null : matching.isError ? matching.error : matching.data} /> : null}
      </Container>
    </>
  );
}
