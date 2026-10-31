"use client";

import { Camera } from "lucide-react";
import * as React from "react";
import { apiUrl } from "@/lib/api";
import { useCapabilities } from "@/lib/capabilities";
import { cn } from "@/lib/utils";

export const JOB_THUMB = "/jobs/{id}/thumbnail.jpg";

/** The job's measured photo cropped to the part; a plain tile when the server has no thumbnails or the job no photo. */
export function JobThumb({ id, className }: { id: string; className?: string }) {
  const caps = useCapabilities();
  const [failed, setFailed] = React.useState(false);
  const box = cn("size-12 shrink-0 overflow-hidden rounded-md border border-border bg-surface-2", className);
  if (!caps.has("get", JOB_THUMB) || failed) {
    return (
      <div className={cn(box, "flex items-center justify-center text-subtle")} aria-hidden>
        <Camera className="size-4" />
      </div>
    );
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element -- an API-rendered JPEG, already sized
    <img src={apiUrl(JOB_THUMB.replace("{id}", encodeURIComponent(id)))} alt="" loading="lazy" decoding="async" onError={() => setFailed(true)} className={cn(box, "object-cover")} />
  );
}
