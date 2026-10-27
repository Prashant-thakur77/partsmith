import { AlertTriangle, CheckCircle2, Contrast, ExternalLink, XCircle } from "lucide-react";
import Link from "next/link";
import type { CaptureReport } from "@/lib/api-types";
import { cn } from "@/lib/utils";

const ICON = { ok: CheckCircle2, warn: AlertTriangle, fail: XCircle } as const;
const TONE = { ok: "text-ok", warn: "text-warn", fail: "text-bad" } as const;
const NAMES: Record<string, string> = {
  markers: "Markers",
  reprojection: "Mat geometry",
  blur: "Sharpness",
  coverage: "Part inside stage",
  tilt: "Camera tilt",
  exposure: "Exposure",
  glare: "Glare",
  moire: "Screen moiré",
  scale: "Scale",
  contrast: "Contrast",
  single_part: "One part only",
};

/** The server capture gate's verdict, check by check, with its plain-words reasons. */
export function CaptureReportView({ report, className }: { report: CaptureReport; className?: string }) {
  const contrast = report.checks.find((c) => c.name === "contrast" && c.severity !== "ok");
  // The server's reason says which stage to switch to; offer it as one click.
  const tone = contrast && /light stage/i.test(contrast.reason) && !/dark stage/i.test(contrast.reason) ? "light" : "dark";
  return (
    <div className={cn("space-y-2", className)}>
      {contrast ? (
        <div
          role="alert"
          className={cn(
            "flex flex-col gap-2.5 rounded-lg border p-3 sm:flex-row sm:items-center sm:justify-between",
            contrast.severity === "fail" ? "border-bad-border bg-bad-soft" : "border-warn-border bg-warn-soft",
          )}
        >
          <div className="flex items-start gap-2">
            <Contrast className={cn("mt-0.5 size-4 shrink-0", contrast.severity === "fail" ? "text-bad" : "text-warn")} aria-hidden />
            <p className="text-[13px] leading-5 font-medium text-fg">{contrast.reason}</p>
          </div>
          <Link
            href={`/mat?stage=${tone}`}
            target="_blank"
            className="inline-flex h-8 shrink-0 items-center gap-1.5 self-start rounded-md bg-inverse px-3 text-[12.5px] font-medium text-inverse-fg hover:opacity-90 sm:self-auto"
          >
            Open mat with {tone} stage <ExternalLink className="size-3.5" aria-hidden />
          </Link>
        </div>
      ) : null}
      <div
        className={cn(
          "flex items-start gap-2 rounded-md border px-3 py-2 text-[13px]",
          report.passed ? "border-ok-border bg-ok-soft text-fg" : "border-bad-border bg-bad-soft text-fg",
        )}
        role="status"
      >
        {report.passed ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden /> : <XCircle className="mt-0.5 size-4 shrink-0 text-bad" aria-hidden />}
        <span>
          <span className="font-medium">{report.passed ? "Capture gate passed" : "Retake this photo"}</span>
          {report.retake_reason ? <span className="text-muted"> — {report.retake_reason}</span> : null}
        </span>
      </div>
      <ul className="grid grid-cols-1 gap-1 sm:grid-cols-2">
        {report.checks.map((c) => {
          const Icon = ICON[c.severity];
          return (
            <li key={c.name} className="flex items-start gap-2 rounded-md px-1 py-1 text-[12px]">
              <Icon className={cn("mt-px size-3.5 shrink-0", TONE[c.severity])} aria-hidden />
              <span className="min-w-0">
                <span className="font-medium text-fg">{NAMES[c.name] ?? c.name}</span>
                <span className="sr-only"> {c.severity === "ok" ? "passed" : c.severity === "warn" ? "warning" : "failed"}</span>
                <span className="block text-muted">{c.reason}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
