"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowRight, Check, ExternalLink, FileDown, FlaskConical, Monitor, Printer } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { PhotoSlot, type SlotValue } from "@/components/fix/photo-slot";
import { Container } from "@/components/layout/page";
import { TranscribeButton } from "@/components/voice-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { api } from "@/lib/api";
import { calibrationDrift, useCalibration } from "@/lib/calibration";
import { FAMILIES } from "@/lib/families";
import { fmtNum, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

const EXAMPLES = [
  "The hook snapped off here — make it 1 mm thicker.",
  "Cupboard latch, the tab broke. Same size, a bit stronger.",
  "Mixer knob, D-shaft. It slips now; make the fit tighter.",
];

function Step({ n, title, done, children, aside }: { n: number; title: string; done?: boolean; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section aria-labelledby={`step-${n}`} className="relative grid gap-4 md:grid-cols-[40px_minmax(0,1fr)]">
      <div className="hidden md:block">
        <div
          className={cn(
            "flex size-8 items-center justify-center rounded-full border font-mono text-[13px]",
            done ? "border-transparent bg-fg text-bg" : "border-border-strong bg-surface text-muted",
          )}
          aria-hidden
        >
          {done ? <Check className="size-4" /> : n}
        </div>
      </div>
      <div className="min-w-0 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id={`step-${n}`} className="text-[17px] font-semibold tracking-tight">
            <span className="mr-2 font-mono text-[13px] text-subtle md:hidden">{n}.</span>
            {title}
          </h2>
          {aside}
        </div>
        {children}
      </div>
    </section>
  );
}

export function FixClient() {
  const router = useRouter();
  const { calibration, ready } = useCalibration();
  const drift = ready && calibration ? calibrationDrift(calibration) : null;
  const calibrated = ready && !!calibration && !drift;
  const [mat, setMat] = React.useState<"screen" | "paper">("screen");
  const [top, setTop] = React.useState<SlotValue>(null);
  const [side, setSide] = React.useState<SlotValue>(null);
  const [mating, setMating] = React.useState<SlotValue>(null);
  const [topGate, setTopGate] = React.useState<boolean | null>(null);
  const [intent, setIntent] = React.useState("");
  const [thickness, setThickness] = React.useState("");
  const [family, setFamily] = React.useState("");

  const start = useMutation({
    mutationFn: () =>
      api.createFixJob({
        top: top!.file,
        side: side?.file,
        mating: mating?.file,
        intent: intent.trim(),
        matKind: mat,
        thicknessMm: thickness.trim() ? Number(thickness) : null,
        familyHint: family || null,
        screenPxPerMm: mat === "screen" ? (calibration?.px_per_mm ?? null) : null,
      }),
    onSuccess: (job) => router.push(`/jobs/${encodeURIComponent(job.id)}`),
  });

  const thicknessBad = thickness.trim() !== "" && !(Number(thickness) > 0 && Number(thickness) < 200);
  const topBlocked = top?.info.checks.some((c) => c.level === "fail") ?? false;
  const canStart = !!top && !topBlocked && !thicknessBad && !start.isPending;

  return (
    <Container className="py-8 sm:py-10">
      <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="max-w-2xl space-y-2">
          <div className="text-[12px] font-medium uppercase tracking-[0.08em] text-accent-text">Fix a broken part</div>
          <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.025em] sm:text-[34px]">From photo to verified part</h1>
          <p className="text-[15px] leading-6 text-muted">
            Three steps, about two minutes. You can watch every measurement and every model iteration live once the job starts.
          </p>
        </div>
        <Button asChild variant="outline">
          <Link href="/jobs/demo">
            <FlaskConical aria-hidden /> Try a synthetic sample
          </Link>
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="space-y-12">
          <Step n={1} title="Choose your mat" done={mat === "paper" || calibrated}>
            <div role="radiogroup" aria-label="Mat type" className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {(
                [
                  { v: "screen", icon: Monitor, title: "Screen mat", badge: "recommended", body: "Your laptop or tablet screen, drawn at 1:1 after a one-time card calibration." },
                  { v: "paper", icon: Printer, title: "Paper mat", badge: "A4 PDF", body: "Print on plain paper at 100 % scale. The PDF has a 50 mm check ruler." },
                ] as const
              ).map((o) => (
                <button
                  key={o.v}
                  type="button"
                  role="radio"
                  aria-checked={mat === o.v}
                  onClick={() => setMat(o.v)}
                  className={cn(
                    "flex gap-3 rounded-lg border bg-surface p-4 text-left transition-colors hover:border-border-strong",
                    mat === o.v ? "border-fg shadow-[0_0_0_1px_var(--fg)]" : "border-border",
                  )}
                >
                  <o.icon className="mt-0.5 size-5 shrink-0 text-muted" aria-hidden />
                  <span className="space-y-1">
                    <span className="flex items-center gap-2 text-[14px] font-medium text-fg">
                      {o.title} <Badge tone={o.v === "screen" ? "accent" : "neutral"}>{o.badge}</Badge>
                    </span>
                    <span className="block text-[13px] leading-5 text-muted">{o.body}</span>
                  </span>
                </button>
              ))}
            </div>
            {mat === "screen" ? (
              <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface-2 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="text-[13px] leading-5">
                  {!ready ? (
                    <span className="text-muted">Checking this screen…</span>
                  ) : calibrated ? (
                    <>
                      <span className="inline-flex items-center gap-1.5 font-medium text-fg">
                        <Check className="size-4 text-ok" aria-hidden /> This screen is calibrated
                      </span>
                      <span className="block font-mono text-[12px] text-muted tnum">{fmtNum(calibration!.px_per_mm, 3)} px/mm</span>
                    </>
                  ) : (
                    <>
                      <span className="font-medium text-fg">{drift ? "Recheck the screen scale" : "Calibrate this screen once"}</span>
                      <span className="block text-muted">{drift ?? "30 seconds with any bank or ID card."}</span>
                    </>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button asChild variant={calibrated ? "outline" : "solid"} size="sm">
                    <Link href="/calibrate?next=/fix">{calibrated ? "Recalibrate" : "Calibrate with a card"}</Link>
                  </Button>
                  <Button asChild variant={calibrated ? "solid" : "outline"} size="sm">
                    <Link href="/mat" target="_blank">
                      Open screen mat <ExternalLink aria-hidden />
                    </Link>
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface-2 p-4 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-[13px] leading-5 text-muted">
                  Print at <strong className="text-fg">100 % / actual size</strong>, then check the 50 mm ruler with anything straight.
                </p>
                <Button asChild variant="solid" size="sm">
                  <a href={api.matPdfUrl("paper-a4")} download>
                    <FileDown aria-hidden /> Download A4 mat (PDF)
                  </a>
                </Button>
              </div>
            )}
            <p className="text-[12.5px] leading-5 text-subtle">
              Tip: open the mat on the laptop, then open this page on your phone to take the photos. White or light-grey part?{" "}
              <Link href="/mat?stage=dark" target="_blank" className="text-accent-text underline underline-offset-2">
                Open the mat with the dark stage
              </Link>
              .
            </p>
          </Step>

          <Step n={2} title="Photograph the part on the mat" done={!!top && topGate === true}>
            <div className="space-y-3">
              <PhotoSlot
                view="top"
                matKind={mat}
                title="Top view"
                hint="Straight down from 20–35 cm, part in the plain middle, black squares visible around it."
                required
                value={top}
                onChange={setTop}
                onGate={setTopGate}
              />
              <PhotoSlot
                view="side"
                matKind={mat}
                title="Side view"
                hint="Lay the part on its side on the mat and shoot straight down — this gives the thickness."
                value={side}
                onChange={setSide}
                compact
              />
              <PhotoSlot
                view="mating"
                title="Where it fits"
                hint="The hole, rail or shaft it attaches to. Helps get the fit right."
                value={mating}
                onChange={setMating}
                gate={false}
                compact
              />
            </div>
          </Step>

          <Step n={3} title="Tell it what you need" done={intent.trim().length > 0}>
            <div className="space-y-2">
              <div className="flex items-end justify-between gap-2">
                <Label htmlFor="intent">What broke, and what should change?</Label>
                <TranscribeButton label="Say it" onText={(t) => setIntent((cur) => (cur ? `${cur} ${t}` : t))} />
              </div>
              <Textarea
                id="intent"
                value={intent}
                onChange={(e) => setIntent(e.target.value)}
                placeholder="e.g. The hook snapped off here — make it 1 mm thicker."
                rows={3}
              />
              <div className="flex flex-wrap gap-1.5">
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex}
                    type="button"
                    onClick={() => setIntent(ex)}
                    className="rounded-full border border-border bg-surface px-2.5 py-1 text-[12px] text-muted hover:border-border-strong hover:text-fg"
                  >
                    {ex}
                  </button>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="thickness">Thickness, if you know it</Label>
                <div className="relative">
                  <Input
                    id="thickness"
                    inputMode="decimal"
                    value={thickness}
                    onChange={(e) => setThickness(e.target.value)}
                    placeholder="optional"
                    aria-invalid={thicknessBad || undefined}
                    aria-describedby="thickness-help"
                    className={cn("pr-10 font-mono tnum", thicknessBad && "border-bad")}
                  />
                  <span className="pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 font-mono text-[12px] text-subtle">mm</span>
                </div>
                <p id="thickness-help" className={cn("text-[12px]", thicknessBad ? "text-bad" : "text-subtle")}>
                  {thicknessBad ? "Enter a number in millimetres." : "Used as a user-stated value and labelled so."}
                </p>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="family">Kind of part</Label>
                <Select id="family" value={family} onChange={(e) => setFamily(e.target.value)} className="w-full">
                  <option value="">Let PartSmith decide</option>
                  {FAMILIES.map((f) => (
                    <option key={f} value={f}>
                      {titleCase(f)}
                    </option>
                  ))}
                </Select>
                <p className="text-[12px] text-subtle">Only a hint — the model can disagree.</p>
              </div>
            </div>
          </Step>
        </div>

        <aside className="lg:sticky lg:top-24 lg:self-start">
          <div className="space-y-4 rounded-xl border border-border bg-surface p-5 shadow-sm">
            <h2 className="text-[14px] font-semibold">Ready to run</h2>
            <ul className="space-y-2 text-[13px]">
              <Check2 ok={mat === "paper" || calibrated} label={mat === "screen" ? "Screen calibrated" : "Paper mat printed at 100 %"} />
              <Check2 ok={!!top && !topBlocked} label="Top photo added" />
              <Check2 ok={topGate === true} label={topGate === false ? "Capture gate: retake suggested" : "Capture gate passed"} warn={topGate === false} />
              <Check2 ok={!!side} label="Side photo (optional)" optional />
              <Check2 ok={intent.trim().length > 0} label="Intent (optional)" optional />
            </ul>
            {start.isError ? <ErrorState error={start.error} compact what="the job" /> : null}
            <Button variant="primary" size="lg" className="w-full" disabled={!canStart} onClick={() => start.mutate()}>
              {start.isPending ? <Spinner className="text-accent-fg" label="Starting" /> : null}
              {start.isPending ? "Starting job…" : "Start the fix"}
              {!start.isPending ? <ArrowRight aria-hidden /> : null}
            </Button>
            <p className="text-[12px] leading-5 text-subtle">
              {topGate === false
                ? "You can still start; the job will stop at the capture stage with the same reasons."
                : "Opens the live workspace. Nothing is published to the registry without your OK."}
            </p>
          </div>
        </aside>
      </div>
    </Container>
  );
}

function Check2({ ok, label, optional, warn }: { ok: boolean; label: string; optional?: boolean; warn?: boolean }) {
  return (
    <li className="flex items-center gap-2">
      <span
        className={cn(
          "flex size-4 items-center justify-center rounded-full border",
          ok ? "border-transparent bg-ok text-white" : warn ? "border-warn bg-warn-soft" : "border-border-strong",
        )}
        aria-hidden
      >
        {ok ? <Check className="size-2.5" strokeWidth={3} /> : null}
      </span>
      <span className={cn(ok ? "text-fg" : optional ? "text-subtle" : "text-muted")}>
        {label}
        <span className="sr-only">{ok ? " — done" : " — not yet"}</span>
      </span>
    </li>
  );
}
