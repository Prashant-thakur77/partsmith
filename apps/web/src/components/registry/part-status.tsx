import { AlertTriangle, BadgeCheck, FileText, Globe } from "lucide-react";
import type { PartStatus } from "@/lib/api-types";
import { fmtErr } from "@/lib/format";
import { Badge } from "../ui/badge";

/** Registry status chip. The status itself is set by the API from the verifier's record. */
export function PartStatusBadge({ status, maxErrorMm }: { status: PartStatus; maxErrorMm?: number | null }) {
  const err = maxErrorMm != null ? <span className="font-mono tnum">· {fmtErr(maxErrorMm)} mm</span> : null;
  if (status === "verified")
    return (
      <Badge tone="ok">
        <BadgeCheck aria-hidden /> Verified {err}
      </Badge>
    );
  if (status === "best_effort")
    return (
      <Badge tone="warn">
        <AlertTriangle aria-hidden /> Best effort {err}
      </Badge>
    );
  if (status === "published")
    return (
      <Badge tone="neutral">
        <Globe aria-hidden /> Published {err}
      </Badge>
    );
  return (
    <Badge tone="neutral">
      <FileText aria-hidden /> Draft
    </Badge>
  );
}
