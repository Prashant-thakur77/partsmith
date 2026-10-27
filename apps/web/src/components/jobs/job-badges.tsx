import { AlertTriangle, BadgeCheck, CircleDashed, Clock, HelpCircle, Loader2, XOctagon } from "lucide-react";
import type { JobSummary } from "@/lib/api-types";
import { fmtNum } from "@/lib/format";
import { Badge } from "../ui/badge";

/** Job state chip. "Verified" only when the job summary says the verifier passed it. */
export function JobStatusBadge({ job }: { job: Pick<JobSummary, "status" | "verified" | "max_error_mm"> }) {
  const err = job.max_error_mm != null ? <span className="font-mono tnum">· {fmtNum(job.max_error_mm)} mm</span> : null;
  switch (job.status) {
    case "queued":
      return (
        <Badge tone="neutral">
          <Clock aria-hidden /> queued
        </Badge>
      );
    case "running":
      return (
        <Badge tone="accent">
          <Loader2 className="animate-spin" aria-hidden /> running
        </Badge>
      );
    case "waiting_for_answer":
      return (
        <Badge tone="info">
          <HelpCircle aria-hidden /> needs your answer
        </Badge>
      );
    case "failed":
      return (
        <Badge tone="bad">
          <XOctagon aria-hidden /> failed
        </Badge>
      );
    case "cancelled":
      return (
        <Badge tone="neutral">
          <CircleDashed aria-hidden /> cancelled
        </Badge>
      );
    case "done":
      return job.verified ? (
        <Badge tone="ok">
          <BadgeCheck aria-hidden /> verified {err}
        </Badge>
      ) : (
        <Badge tone="warn">
          <AlertTriangle aria-hidden /> best effort {err}
        </Badge>
      );
  }
}
