"use client";

import { AlertTriangle, BadgeCheck, CircleDashed, XOctagon } from "lucide-react";
import * as React from "react";
import type { Verification } from "@/lib/api-types";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Tooltip } from "./tooltip";

/**
 * The Verified badge. Its only input is the verifier's `Verification` record (code-decided); nothing else can make it green.
 * Stamps in when the status flips to verified while mounted.
 */
export function VerifiedBadge({
  verification,
  size = "md",
  pending = false,
  className,
}: {
  verification: Verification | null | undefined;
  size?: "sm" | "md" | "lg";
  pending?: boolean;
  className?: string;
}) {
  const status = verification ? (verification.verified ? "verified" : verification.status) : pending ? "pending" : "none";
  const prev = React.useRef(status);
  const [stamp, setStamp] = React.useState(false);
  React.useEffect(() => {
    if (status === "verified" && prev.current !== "verified" && prev.current !== "none") setStamp(true);
    prev.current = status;
  }, [status]);

  const err = verification?.max_error_mm;
  const tests = verification?.tests ?? [];
  const passed = tests.filter((t) => t.passed).length;

  const look = {
    verified: { icon: BadgeCheck, text: "Verified", cls: "border-ok-border bg-ok-soft text-ok" },
    best_effort: { icon: AlertTriangle, text: "Best effort", cls: "border-warn-border bg-warn-soft text-warn" },
    failed: { icon: XOctagon, text: "Failed", cls: "border-bad-border bg-bad-soft text-bad" },
    pending: { icon: CircleDashed, text: "Verifying…", cls: "border-border bg-surface-2 text-muted" },
    none: { icon: CircleDashed, text: "Not verified", cls: "border-border bg-surface-2 text-muted" },
  }[status];
  const Icon = look.icon;
  const sizes = {
    sm: "h-6 gap-1 px-2 text-[11px] [&_svg]:size-3.5",
    md: "h-8 gap-1.5 px-2.5 text-[13px] [&_svg]:size-4",
    lg: "h-10 gap-2 px-3.5 text-[15px] [&_svg]:size-5",
  }[size];

  const tip = verification ? (
    <div className="space-y-1.5">
      <div className="font-medium">
        {verification.verified ? "Code verified this model against the photo." : "The verifier did not pass this model."}
      </div>
      <div className="font-mono tnum">
        max error {err != null ? `${fmtNum(err)} mm` : "—"} · limit {fmtNum(verification.thresholds.hausdorff_mm)} mm
      </div>
      {tests.length ? <div className="font-mono tnum">{passed}/{tests.length} part tests passed</div> : null}
      {verification.reasons.slice(0, 3).map((r) => (
        <div key={r} className="opacity-80">
          · {r}
        </div>
      ))}
    </div>
  ) : (
    "No verification record yet. Only the verifier can mark a part verified."
  );

  return (
    <Tooltip content={tip}>
      <span
        tabIndex={0}
        role="status"
        aria-label={`${look.text}${err != null ? `, max error ${fmtNum(err)} millimetres` : ""}`}
        className={cn(
          "inline-flex shrink-0 cursor-help items-center rounded-md border font-semibold whitespace-nowrap select-none",
          look.cls,
          sizes,
          stamp && "animate-stamp",
          status === "pending" && "[&_svg]:animate-spin",
          className,
        )}
      >
        <Icon aria-hidden />
        {look.text}
        {err != null && status !== "pending" && status !== "none" ? (
          <span className="font-mono font-medium tnum">· {fmtNum(err)} mm</span>
        ) : null}
      </span>
    </Tooltip>
  );
}
