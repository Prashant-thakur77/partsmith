"use client";

import { useMutation } from "@tanstack/react-query";
import { Archive, Box, Download, FileCode2, FileText, Image as ImageIcon, Layers, Link2, Lock, Printer, QrCode, ScanLine, Sparkles, Wrench } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { api, artifactUrl } from "@/lib/api";
import type { PassportLink, Verification } from "@/lib/api-types";
import { noteCouponDownload } from "@/lib/coupon-fit";
import { fitWarning } from "@/lib/mate-fit";
import { useT } from "@/lib/i18n";
import { PRINTABLE_KINDS, withAck } from "@/lib/ship";
import { slicerHandoff } from "@/lib/slicers";
import { useOrigin } from "@/lib/use-origin";
import { groupPassportId, passportLink, qrFileName } from "@/lib/passport";
import { ExportGateNotice, gateReason, useExportGate } from "../export-gate";
import { Button } from "../ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "../ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "../ui/dropdown-menu";
import { ErrorState } from "../ui/error-state";
import { ModeBadge } from "../ui/provenance";
import { Badge } from "../ui/badge";
import { Spinner } from "../ui/spinner";
import { toast } from "../ui/toast";

const ITEMS = [
  { kind: "stl", label: "STL", sub: "mesh for any slicer", icon: Box, file: "part.stl" },
  { kind: "threemf", label: "3MF", sub: "with print settings", icon: Layers, file: "part.3mf" },
  { kind: "step", label: "STEP", sub: "editable in any CAD", icon: Box, file: "part.step" },
  { kind: "code", label: "part.py", sub: "parametric CadQuery", icon: FileCode2, file: "part.py" },
  { kind: "template_pdf", label: "1:1 paper template", sub: "PDF, print at 100 %", icon: FileText, file: "template.pdf" },
  { kind: "repair_card", label: "Repair card", sub: "printable summary", icon: Wrench, file: "repair-card.pdf" },
  { kind: "coupon", label: "Fit-test coupon", sub: "small test print for the fit", icon: Box, file: "coupon.stl" },
  { kind: "zip", label: "Everything (.zip)", sub: "files, part.py, README, licence", icon: Archive, file: "partsmith-bundle.zip" },
  { kind: "verification", label: "verification.json", sub: "the verifier's record", icon: FileText, file: "verification.json" },
] as const;

/**
 * Export menu with the export gate: verified models download in one click; best-effort ones first show why they are
 * locked, suggest the fit-test coupon and need an explicit acknowledgement.
 */
export function ExportMenu({
  artifacts,
  disabled,
  verification,
  passport,
}: {
  artifacts: Record<string, string>;
  disabled?: boolean;
  verification?: Verification | null;
  /** The finished job's repair passport (the id on its repair card's QR code). */
  passport?: PassportLink;
}) {
  const any = ITEMS.some((i) => artifacts[i.kind]);
  const gate = useExportGate(verification);
  const fitWarn = fitWarning(verification);
  const { t } = useT();
  const origin = useOrigin();
  const [gateOpen, setGateOpen] = React.useState(false);
  const acked = gate.state === "best_effort" && gate.ack;
  const slicer = slicerHandoff(withAck(artifactUrl(artifacts.threemf), acked), origin, gate.state, gate.ack);
  if (gate.locked && !gate.ack)
    return (
      <Dialog open={gateOpen} onOpenChange={setGateOpen}>
        <DialogTrigger asChild>
          <Button variant="solid" size="sm" disabled={disabled || !any}>
            <Lock aria-hidden /> {t("ws.export")}
          </Button>
        </DialogTrigger>
        <DialogContent>
          <DialogTitle>{t("gate.title")}</DialogTitle>
          <DialogDescription className="sr-only">{gateReason(verification, t)}</DialogDescription>
          <ExportGateNotice verification={verification} couponUrl={artifactUrl(artifacts.coupon)} ack={gate.ack} onAck={(v) => gate.setAck(v)} />
        </DialogContent>
      </Dialog>
    );
  return (
    <DropdownMenu defaultOpen={gate.locked && gate.ack}>
      <DropdownMenuTrigger asChild>
        <Button variant="solid" size="sm" disabled={disabled || !any}>
          <Download aria-hidden /> {t("ws.export")}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel>Download</DropdownMenuLabel>
        {fitWarn ? (
          <p role="note" className="mx-2 mb-1.5 rounded-md border border-bad-border bg-bad-soft/40 px-2 py-1.5 text-[12px] leading-5 text-fg">
            {fitWarn}
          </p>
        ) : null}
        {ITEMS.map((i) => {
          const raw = artifactUrl(artifacts[i.kind]);
          const url = PRINTABLE_KINDS.has(i.kind) ? withAck(raw, acked) : raw;
          return (
            <DropdownMenuItem key={i.kind} disabled={!url} asChild={!!url}>
              {url ? (
                <a href={url} download={i.file} onClick={i.kind === "coupon" ? noteCouponDownload : undefined}>
                  <i.icon aria-hidden />
                  <span className="flex-1">
                    <span className="block">{i.label}</span>
                    <span className="block text-[11px] text-subtle">{i.sub}</span>
                  </span>
                </a>
              ) : (
                <>
                  <i.icon aria-hidden />
                  <span className="flex-1">
                    <span className="block">{i.label}</span>
                    <span className="block text-[11px] text-subtle">not produced yet</span>
                  </span>
                </>
              )}
            </DropdownMenuItem>
          );
        })}
        {slicer.state === "ready" ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>Open the 3MF in a slicer</DropdownMenuLabel>
            {slicer.links.map(({ slicer: s, href }) => (
              <DropdownMenuItem key={s.id} asChild>
                <a href={href ?? slicer.fileUrl} {...(href ? {} : { download: "part.3mf" })}>
                  {href ? <Printer aria-hidden /> : <Download aria-hidden />}
                  <span className="flex-1">
                    <span className="block">{s.name}</span>
                    <span className="block text-[11px] text-subtle">{href ? "opens the app, which downloads the file" : s.howTo}</span>
                  </span>
                </a>
              </DropdownMenuItem>
            ))}
          </>
        ) : null}
        {passport ? <PassportItems passport={passport} origin={origin} /> : null}
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/calibrate">
            <ScanLine aria-hidden /> Calibrate screen
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** The job's repair passport in the export menu: copy its link, download its QR code, open its page. */
function PassportItems({ passport, origin }: { passport: PassportLink; origin: string }) {
  const href = passportLink(origin, passport.id);
  const copy = () => {
    void navigator.clipboard
      ?.writeText(href)
      .then(() => toast("Passport link copied", { description: href, tone: "ok" }))
      .catch(() => toast("Could not copy", { description: href }));
  };
  return (
    <>
      <DropdownMenuSeparator />
      <DropdownMenuLabel>
        Repair passport <span className="font-mono tracking-[0.08em] text-fg">{groupPassportId(passport.id)}</span>
      </DropdownMenuLabel>
      <DropdownMenuItem onSelect={copy}>
        <Link2 aria-hidden />
        <span className="flex-1">
          <span className="block">Copy link</span>
          <span className="block text-[11px] text-subtle">broke again? one scan reprints it</span>
        </span>
      </DropdownMenuItem>
      <DropdownMenuItem asChild>
        <a href={artifactUrl(passport.qr_png_url)} download={qrFileName(passport.id, "png")}>
          <QrCode aria-hidden /> <span className="flex-1">Passport QR (PNG)</span>
        </a>
      </DropdownMenuItem>
      <DropdownMenuItem asChild>
        <a href={artifactUrl(passport.qr_svg_url)} download={qrFileName(passport.id, "svg")}>
          <QrCode aria-hidden /> <span className="flex-1">Passport QR (SVG)</span>
        </a>
      </DropdownMenuItem>
    </>
  );
}

/** A mock or placeholder preview (no image model ran): never shown as if it were a picture of the fix. */
export function isPlaceholderPreview(p: { mode: string; label: string }): boolean {
  return p.mode === "mock" || /\bmock\b|placeholder|not ai-generated/i.test(p.label);
}

/** "See the fix": Muse Image composites the new part into the original photo. Always labelled as a generated preview. */
export function PreviewDialog({ jobId, photoUrl, disabled }: { jobId: string; photoUrl?: string; disabled?: boolean }) {
  const preview = useMutation({ mutationFn: () => api.preview(jobId) });
  return (
    <Dialog onOpenChange={(o) => o && !preview.data && !preview.isPending && preview.mutate()}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" disabled={disabled}>
          <Sparkles aria-hidden /> See the fix
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-3xl">
        <DialogTitle>See the fix</DialogTitle>
        <DialogDescription>The new part shown in your original photo — an illustration only, never a measurement.</DialogDescription>
        {preview.isPending ? (
          <div className="flex aspect-[4/3] items-center justify-center rounded-lg border border-border bg-surface-2">
            <Spinner label="Generating preview" />
          </div>
        ) : preview.isError ? (
          <ErrorState error={preview.error} compact what="the preview" onRetry={() => preview.mutate()} />
        ) : preview.data && isPlaceholderPreview(preview.data) ? (
          <div role="note" className="flex aspect-[16/7] flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-surface-2 px-6 text-center">
            <ImageIcon className="size-6 text-subtle" aria-hidden />
            <p className="text-[14px] font-medium text-fg">No picture of the fix on this server</p>
            <p className="max-w-md text-[12.5px] text-muted">
              The image model is not being called here (mock mode), so there is only a placeholder and it is not shown. The 3D model,
              the measurements and the verdict on this page are the real result.
            </p>
            <ModeBadge mode={preview.data.mode} />
          </div>
        ) : preview.data ? (
          <div className="space-y-2">
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {photoUrl ? (
                <figure className="space-y-1">
                  {/* eslint-disable-next-line @next/next/no-img-element -- API artifact */}
                  <img src={photoUrl} alt="Original photo" className="aspect-[4/3] w-full rounded-md border border-border object-cover" />
                  <figcaption className="text-[12px] text-muted">Your photo</figcaption>
                </figure>
              ) : null}
              <figure className="space-y-1">
                <div className="relative">
                  {/* eslint-disable-next-line @next/next/no-img-element -- API artifact */}
                  <img src={artifactUrl(preview.data.url)} alt={`${preview.data.label || "Preview"} of the repaired part`} className="aspect-[4/3] w-full rounded-md border border-border object-cover" />
                  <div className="absolute top-2 left-2 flex gap-1">
                    <Badge tone="inverse">
                      <ImageIcon aria-hidden /> {preview.data.label || "AI preview"}
                    </Badge>
                    <ModeBadge mode={preview.data.mode} hideLive />
                  </div>
                </div>
                <figcaption className="text-[12px] text-muted">{preview.data.label || "AI preview"} · illustration, not a measurement</figcaption>
              </figure>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
