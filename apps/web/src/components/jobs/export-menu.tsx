"use client";

import { useMutation } from "@tanstack/react-query";
import { Archive, Box, Download, FileCode2, FileText, Image as ImageIcon, Layers, Lock, ScanLine, Sparkles, Wrench } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { api, artifactUrl } from "@/lib/api";
import type { Verification } from "@/lib/api-types";
import { useT } from "@/lib/i18n";
import { ExportGateNotice, gateReason, useExportGate } from "../export-gate";
import { Button } from "../ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "../ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "../ui/dropdown-menu";
import { ErrorState } from "../ui/error-state";
import { ModeBadge } from "../ui/provenance";
import { Badge } from "../ui/badge";
import { Spinner } from "../ui/spinner";

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
export function ExportMenu({ artifacts, disabled, verification }: { artifacts: Record<string, string>; disabled?: boolean; verification?: Verification | null }) {
  const any = ITEMS.some((i) => artifacts[i.kind]);
  const gate = useExportGate(verification);
  const { t } = useT();
  const [gateOpen, setGateOpen] = React.useState(false);
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
        {ITEMS.map((i) => {
          const url = artifactUrl(artifacts[i.kind]);
          return (
            <DropdownMenuItem key={i.kind} disabled={!url} asChild={!!url}>
              {url ? (
                <a href={url} download={i.file}>
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
