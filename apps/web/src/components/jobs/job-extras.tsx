"use client";

import { Download, Images, Video } from "lucide-react";
import * as React from "react";
import { artifactUrl } from "@/lib/api";
import type { ArtifactEvent } from "@/lib/api-types";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { installPanel, installStepsNote } from "@/lib/verdict-notes";
import { Badge } from "../ui/badge";
import { WipeSlider } from "./wipe-slider";

function latest(events: ArtifactEvent[], kind: string): ArtifactEvent | undefined {
  return [...events].reverse().find((e) => e.kind === kind);
}

type Panel = { url: string; label: string; step: number | null; of: number | null; text: string; mock: boolean };

/** Every panel of the latest install card, in step order (a re-run replaces earlier panels with the same step). */
function installPanels(events: ArtifactEvent[]): Panel[] {
  const bySteps = new Map<number, Panel>();
  const loose: Panel[] = [];
  for (const e of events) {
    if (e.kind !== "install_card") continue;
    const p = installPanel(e.label ?? "");
    if (p) bySteps.set(p.step, { url: e.url, label: e.label ?? "", ...p });
    else loose.push({ url: e.url, label: e.label ?? "", step: null, of: null, text: (e.label ?? "").replace(/^install card\s*/i, ""), mock: /\(mock\)/i.test(e.label ?? "") });
  }
  if (bySteps.size) return [...bySteps.values()].sort((a, b) => a.step! - b.step!);
  return loose.slice(-1);
}

/**
 * Round-2 artifacts when a job has them: the orbit preview clip, the Muse Image broken-region proposal (with the code
 * gate's verdict from its label), and every panel of the install card, labelled as a generated illustration. Nothing
 * renders for jobs without them.
 */
export function JobExtras({ artifactEvents, rectified, family }: { artifactEvents: ArtifactEvent[]; rectified?: string; family?: string | null }) {
  const { t } = useT();
  const video = latest(artifactEvents, "video");
  const recon = latest(artifactEvents, "reconstruction");
  const card = latest(artifactEvents, "install_card");
  const panels = installPanels(artifactEvents);
  const stepsNote = installStepsNote(family, panels.map((p) => p.text));
  if (!video && !recon && !card) return null;
  return (
    <div className="grid grid-cols-1 gap-4 xl:order-5 xl:col-span-3 lg:grid-cols-3">
      {video ? (
        <section aria-label={t("ws.orbit")} className="overflow-hidden rounded-lg border border-border bg-surface">
          <header className="flex items-center gap-2 border-b border-border px-4 py-2.5 text-[13px] font-semibold">
            <Video className="size-4 text-muted" aria-hidden /> {t("ws.orbit")}
          </header>
          <video src={artifactUrl(video.url)} muted loop playsInline controls preload="metadata" className="aspect-video w-full bg-black object-contain" />
          {video.label ? <p className="px-4 py-2 text-[12px] text-muted">{video.label}</p> : null}
        </section>
      ) : null}
      {recon ? (
        <section aria-label={t("ws.reconstruction")} className="overflow-hidden rounded-lg border border-border bg-surface">
          <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
            <span className="text-[13px] font-semibold">{t("ws.reconstruction")}</span>
            <span className="flex gap-1">
              <Badge tone="mock">generated</Badge>
              {recon.label ? (
                /rejected/i.test(recon.label) ? <Badge tone="bad">code gate: rejected</Badge> : /accepted|passed/i.test(recon.label) ? <Badge tone="ok">code gate: accepted</Badge> : null
              ) : null}
            </span>
          </header>
          {rectified ? (
            <WipeSlider before={artifactUrl(rectified)!} after={artifactUrl(recon.url)!} beforeLabel="Photo" afterLabel="Proposal" className="aspect-[4/3]" />
          ) : (
            // eslint-disable-next-line @next/next/no-img-element -- API artifact
            <img src={artifactUrl(recon.url)} alt="Proposed completion of the broken region" className="aspect-[4/3] w-full object-contain" />
          )}
          <p className="px-4 py-2 font-mono text-[12px] text-muted">{recon.label || "gate result not reported"}</p>
        </section>
      ) : null}
      {card ? (
        <section aria-label={t("ws.installCard")} className="overflow-hidden rounded-lg border border-border bg-surface lg:col-span-3">
          <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
            <span className="flex flex-wrap items-center gap-2 text-[13px] font-semibold">
              <Images className="size-4 text-muted" aria-hidden /> {t("ws.installCard")}
              <Badge tone="mock" title="Drawn by an image model from the top photo and the model's outline. Not a photo, not a measurement.">
                {panels.some((p) => p.mock) ? "mock illustration (no image model ran)" : "AI-generated illustration"}
              </Badge>
            </span>
            <span className="text-[12px] text-subtle">
              {panels.length} panel{panels.length === 1 ? "" : "s"}
            </span>
          </header>
          <ol className={cn("grid grid-cols-1 gap-px bg-border", panels.length > 1 && "sm:grid-cols-3")} aria-label="Install steps">
            {panels.map((p, i) => (
              <li key={p.url} className="flex flex-col bg-surface">
                {/* eslint-disable-next-line @next/next/no-img-element -- API artifact */}
                <img src={artifactUrl(p.url)} alt={`Install step ${p.step ?? i + 1}, generated illustration${p.text ? `: ${p.text}` : ""}`} loading="lazy" className="w-full object-contain" />
                <div className="flex items-start justify-between gap-2 px-3 py-2 text-[12px]">
                  <span className="text-muted">
                    {p.step != null ? <span className="font-medium text-fg">Step {p.step}{p.of ? ` of ${p.of}` : ""}: </span> : null}
                    {p.text || p.label}
                  </span>
                  <a href={artifactUrl(p.url)} download className="inline-flex shrink-0 items-center gap-1 font-medium text-accent-text hover:underline" aria-label={`Download step ${p.step ?? i + 1}`}>
                    <Download className="size-3.5" aria-hidden />
                  </a>
                </div>
              </li>
            ))}
          </ol>
          {stepsNote ? <p className="border-t border-border px-4 py-2 text-[12px] text-muted">{stepsNote}</p> : null}
        </section>
      ) : null}
    </div>
  );
}
