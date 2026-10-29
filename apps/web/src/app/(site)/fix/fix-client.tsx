"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowRight, Check, ExternalLink, FileDown, Monitor, Printer } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { MATE_TAP_KINDS, PhotoSlot, type SlotValue, type TapPoint } from "@/components/fix/photo-slot";
import { VideoSlot } from "@/components/fix/video-slot";
import { VoiceNoteSlot } from "@/components/fix/voice-note-slot";
import { useCapabilities } from "@/lib/capabilities";
import { Container } from "@/components/layout/page";
import { TranscribeButton } from "@/components/voice-button";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { ApiError, api } from "@/lib/api";
import { cityParam } from "@/lib/buy-or-print";
import { uploadRefusal, voiceNoteProblem } from "@/lib/evidence-notes";
import { calibrationDrift, useCalibration } from "@/lib/calibration";
import { FAMILIES } from "@/lib/families";
import { fixPrefill } from "@/lib/passport";
import type { MateTapKind, TopTapKind } from "@/lib/mate-fit";
import { fmtNum, titleCase } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { radioGroupKeys } from "@/lib/a11y";

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
  const { t } = useT();
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
  const [orbit, setOrbit] = React.useState<File | null>(null);
  const [points, setPoints] = React.useState<TapPoint[]>([]);
  const [matingPoints, setMatingPoints] = React.useState<TapPoint[]>([]);
  const [voiceNote, setVoiceNote] = React.useState<File | null>(null);
  const [city, setCity] = React.useState("");
  // "It broke in a new place" on a passport page links here with the family and an intent prefilled.
  React.useEffect(() => {
    const pre = fixPrefill(window.location.search, FAMILIES);
    if (pre.family) setFamily(pre.family);
    if (pre.intent) setIntent(pre.intent);
  }, []);
  const caps = useCapabilities();
  const fixFields = caps.fields("post", "/jobs/fix");
  const canOrbit = fixFields.has("orbit");
  const canPoints = fixFields.has("points");
  const canNarrate = canOrbit && fixFields.has("narration");
  const canCity = fixFields.has("city");
  // The voice note travels with the walk-around clip; without a clip the server has nothing to narrate.
  const sendNote = canNarrate && !!orbit && !!voiceNote;
  const noteProblem = sendNote ? voiceNoteProblem(voiceNote!.type, voiceNote!.size) : null;

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
        orbit: canOrbit ? orbit : null,
        points: canPoints ? (points as TapPoint<TopTapKind>[]) : null,
        matingPoints: canPoints ? (matingPoints as TapPoint<MateTapKind>[]) : null,
        narration: sendNote ? voiceNote : null,
        city: canCity ? cityParam(city) : null,
      }),
    onSuccess: (job) => router.push(`/jobs/${encodeURIComponent(job.id)}`),
  });

  const thicknessBad = thickness.trim() !== "" && !(Number(thickness) > 0 && Number(thickness) < 200);
  const topBlocked = top?.info.checks.some((c) => c.level === "fail") ?? false;
  const canStart = !!top && !topBlocked && !thicknessBad && !noteProblem && !start.isPending;
  const refusal = start.error instanceof ApiError ? uploadRefusal(start.error.status, start.error.message) : null;

  return (
    <Container className="pb-8 sm:pb-10">
      <div className="grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="space-y-12">
          <Step n={1} title={t("fix.step1")} done={mat === "paper" || calibrated}>
            <div role="radiogroup" onKeyDown={radioGroupKeys} aria-label="Mat type" className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {(
                [
                  { v: "screen", icon: Monitor, title: t("fix.screenMat"), badge: t("fix.recommended"), body: t("fix.screenMatBody") },
                  { v: "paper", icon: Printer, title: t("fix.paperMat"), badge: "A4 PDF", body: t("fix.paperMatBody") },
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
                        <Check className="size-4 text-ok" aria-hidden /> {t("fix.calibrated")}
                      </span>
                      <span className="block font-mono text-[12px] text-muted tnum">{fmtNum(calibration!.px_per_mm, 3)} px/mm</span>
                    </>
                  ) : (
                    <>
                      <span className="font-medium text-fg">{drift ? t("fix.recheck") : t("fix.calibrateOnce")}</span>
                      <span className="block text-muted">{drift ?? t("fix.calibrateOnceBody")}</span>
                    </>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button asChild variant={calibrated ? "outline" : "solid"} size="sm">
                    <Link href="/calibrate?next=/fix">{calibrated ? t("fix.recalibrate") : t("fix.calibrate")}</Link>
                  </Button>
                  <Button asChild variant={calibrated ? "solid" : "outline"} size="sm">
                    <Link href="/mat" target="_blank">
                      {t("fix.openMat")} <ExternalLink aria-hidden />
                    </Link>
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-3 rounded-lg border border-border bg-surface-2 p-4 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-[13px] leading-5 text-muted">
                  {t("fix.printHint")}
                </p>
                <Button asChild variant="solid" size="sm">
                  <a href={api.matPdfUrl("paper-a4")} download>
                    <FileDown aria-hidden /> {t("fix.downloadPdf")}
                  </a>
                </Button>
              </div>
            )}
            <p className="text-[12.5px] leading-5 text-subtle">
              {t("fix.tip")}{" "}
              <Link href="/mat?stage=dark" target="_blank" className="text-accent-text underline underline-offset-2">
                {t("fix.darkStageLink")}
              </Link>
              .
            </p>
          </Step>

          <Step n={2} title={t("fix.step2")} done={!!top && topGate === true}>
            <div className="space-y-3">
              <PhotoSlot
                view="top"
                matKind={mat}
                title={t("fix.top")}
                hint={t("fix.topHint")}
                required
                value={top}
                onChange={(v) => {
                  setTop(v);
                  setPoints([]);
                }}
                points={points}
                onPoints={setPoints}
                pointsHint={t("fix.points", { n: points.length }) + (canPoints ? "" : " " + t("fix.pointsLocal"))}
                onGate={setTopGate}
              />
              <PhotoSlot
                view="side"
                matKind={mat}
                title={t("fix.side")}
                hint={t("fix.sideHint")}
                value={side}
                onChange={setSide}
                compact
              />
              <PhotoSlot
                view="mating"
                title={t("fix.mating")}
                hint={t("fix.matingHint")}
                value={mating}
                onChange={(v) => {
                  setMating(v);
                  setMatingPoints([]);
                }}
                gate={false}
                compact
                points={matingPoints}
                onPoints={setMatingPoints}
                tapKinds={MATE_TAP_KINDS}
                pointsHint={t("fix.matingPoints", { n: matingPoints.length }) + (canPoints ? "" : " " + t("fix.pointsLocal"))}
              />
              {canOrbit ? <VideoSlot title={t("fix.orbit")} hint={t("fix.orbitHint")} value={orbit} onChange={setOrbit} /> : null}
              {canNarrate ? <VoiceNoteSlot value={voiceNote} onChange={setVoiceNote} hasClip={!!orbit} /> : null}
            </div>
          </Step>

          <Step n={3} title={t("fix.step3")} done={intent.trim().length > 0}>
            <div className="space-y-2">
              <div className="flex items-end justify-between gap-2">
                <Label htmlFor="intent">{t("fix.intentLabel")}</Label>
                <TranscribeButton label={t("fix.sayIt")} onText={(x) => setIntent((cur) => (cur ? `${cur} ${x}` : x))} />
              </div>
              <Textarea
                id="intent"
                value={intent}
                onChange={(e) => setIntent(e.target.value)}
                placeholder={t("fix.intentPlaceholder")}
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
                <Label htmlFor="thickness">{t("fix.thickness")}</Label>
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
                  {thicknessBad ? t("fix.thicknessBad") : t("fix.thicknessHelp")}
                </p>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="family">{t("fix.kind")}</Label>
                <Select id="family" value={family} onChange={(e) => setFamily(e.target.value)} className="w-full">
                  <option value="">{t("fix.kindAuto")}</option>
                  {FAMILIES.map((f) => (
                    <option key={f} value={f}>
                      {titleCase(f)}
                    </option>
                  ))}
                </Select>
                <p className="text-[12px] text-subtle">Only a hint — the model can disagree.</p>
              </div>
              {canCity ? (
                <div className="space-y-1.5 sm:col-span-2">
                  <Label htmlFor="city">{t("fix.city")}</Label>
                  <Input
                    id="city"
                    value={city}
                    maxLength={80}
                    autoComplete="address-level2"
                    onChange={(e) => setCity(e.target.value)}
                    placeholder="optional"
                    aria-describedby="city-help"
                    className="sm:max-w-sm"
                  />
                  <p id="city-help" className="text-[12px] text-subtle">
                    {t("fix.cityHint")}
                  </p>
                </div>
              ) : null}
            </div>
          </Step>
        </div>

        <aside className="lg:sticky lg:top-24 lg:self-start">
          <div className="space-y-4 rounded-xl border border-border bg-surface p-5 shadow-sm">
            <h2 className="text-[14px] font-semibold">{t("fix.ready")}</h2>
            <ul className="space-y-2 text-[13px]">
              <Check2 ok={mat === "paper" || calibrated} label={mat === "screen" ? t("fix.checkScreen") : t("fix.checkPaper")} />
              <Check2 ok={!!top && !topBlocked} label={t("fix.checkTop")} />
              <Check2 ok={topGate === true} label={topGate === false ? t("fix.checkGateRetake") : t("fix.checkGate")} warn={topGate === false} />
              <Check2 ok={!!side} label={t("fix.checkSide")} optional />
              <Check2 ok={intent.trim().length > 0} label={t("fix.checkIntent")} optional />
            </ul>
            {refusal ? (
              <p role="alert" className="rounded-md border border-bad-border bg-bad-soft/40 px-3 py-2 text-[12.5px] leading-5 text-fg">
                <span className="mr-1 font-mono text-[11.5px] text-bad">{(start.error as ApiError).status}</span>
                {refusal}
              </p>
            ) : null}
            {start.isError && !refusal ? <ErrorState error={start.error} compact what="the job" /> : null}
            {noteProblem ? <p className="text-[12px] text-bad">{noteProblem}</p> : null}
            <Button variant="primary" size="lg" className="w-full" disabled={!canStart} onClick={() => start.mutate()}>
              {start.isPending ? <Spinner className="text-accent-fg" label="Starting" /> : null}
              {start.isPending ? t("fix.starting") : t("fix.start")}
              {!start.isPending ? <ArrowRight aria-hidden /> : null}
            </Button>
            <p className="text-[12px] leading-5 text-subtle">
              {topGate === false
                ? t("fix.startNoteRetake")
                : t("fix.startNote")}
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
