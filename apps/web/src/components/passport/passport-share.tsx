"use client";

/**
 * The repair passport id of a part or a job: the id, a copyable link to /p/{id} and the QR code as PNG or SVG
 * (rendered by the API with reportlab's encoder). The repair card PDF carries the same QR.
 */
import { Download, QrCode } from "lucide-react";
import { artifactUrl } from "@/lib/api";
import type { PassportLink } from "@/lib/api-types";
import { groupPassportId, passportLink, qrFileName } from "@/lib/passport";
import { useOrigin } from "@/lib/use-origin";
import { cn } from "@/lib/utils";
import { CopyButton } from "../ui/copy-button";

export function PassportShare({ passport, title, className }: { passport: PassportLink; title?: string; className?: string }) {
  const origin = useOrigin();
  const href = passportLink(origin, passport.id);
  const svg = artifactUrl(passport.qr_svg_url);
  const png = artifactUrl(passport.qr_png_url);
  return (
    <section aria-labelledby={`passport-${passport.id}`} className={cn("flex min-w-0 items-start gap-3", className)}>
      {/* eslint-disable-next-line @next/next/no-img-element -- QR rendered by the API */}
      <img src={svg} alt={`QR code to the repair passport of ${title || "this part"}`} width={72} height={72} className="size-[72px] shrink-0 rounded-md border border-border bg-white p-1" loading="lazy" />
      <div className="min-w-0 flex-1 space-y-1">
        <h3 id={`passport-${passport.id}`} className="flex items-center gap-1.5 text-[13px] font-medium text-fg">
          <QrCode className="size-3.5 text-muted" aria-hidden /> Repair passport
        </h3>
        <p className="font-mono text-[18px] leading-6 font-semibold tracking-[0.08em] text-fg" aria-label={`Passport id ${passport.id.split("").join(" ")}`}>
          {groupPassportId(passport.id)}
        </p>
        <p className="text-[12px] leading-5 text-muted">Broke again? Scan or type this id to reprint it, with your printer&apos;s clearance.</p>
        <div className="flex flex-wrap items-center gap-1">
          <CopyButton value={href} label="Copy link" className="-ml-2" />
          <a href={png} download={qrFileName(passport.id, "png")} className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[12px] font-medium text-muted hover:bg-surface-3 hover:text-fg">
            <Download className="size-3.5" aria-hidden /> QR PNG
          </a>
          <a href={svg} download={qrFileName(passport.id, "svg")} className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[12px] font-medium text-muted hover:bg-surface-3 hover:text-fg">
            <Download className="size-3.5" aria-hidden /> QR SVG
          </a>
        </div>
      </div>
    </section>
  );
}
