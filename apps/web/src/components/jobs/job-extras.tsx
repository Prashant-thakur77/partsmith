"use client";

import { Download, Images, Video } from "lucide-react";
import * as React from "react";
import { artifactUrl } from "@/lib/api";
import type { ArtifactEvent } from "@/lib/api-types";
import { useT } from "@/lib/i18n";
import { Badge } from "../ui/badge";
import { WipeSlider } from "./wipe-slider";

function latest(events: ArtifactEvent[], kind: string): ArtifactEvent | undefined {
  return [...events].reverse().find((e) => e.kind === kind);
}

/**
 * Round-2 artifacts when a job has them: the orbit preview clip, the Muse Image broken-region proposal (with the code
 * gate's verdict from its label), and the 3-panel install card. Nothing renders for jobs without them.
 */
export function JobExtras({ artifactEvents, rectified }: { artifactEvents: ArtifactEvent[]; rectified?: string }) {
  const { t } = useT();
  const video = latest(artifactEvents, "video");
  const recon = latest(artifactEvents, "reconstruction");
  const card = latest(artifactEvents, "install_card");
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
        <section aria-label={t("ws.installCard")} className="overflow-hidden rounded-lg border border-border bg-surface">
          <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
            <span className="flex items-center gap-2 text-[13px] font-semibold">
              <Images className="size-4 text-muted" aria-hidden /> {t("ws.installCard")}
            </span>
            <a href={artifactUrl(card.url)} download className="inline-flex items-center gap-1 text-[12px] font-medium text-accent-text hover:underline">
              <Download className="size-3.5" aria-hidden /> Download
            </a>
          </header>
          {/* eslint-disable-next-line @next/next/no-img-element -- API artifact */}
          <img src={artifactUrl(card.url)} alt="Install card: three panels showing where the part goes" className="w-full object-contain" />
          {card.label ? <p className="px-4 py-2 text-[12px] text-muted">{card.label}</p> : null}
        </section>
      ) : null}
    </div>
  );
}
