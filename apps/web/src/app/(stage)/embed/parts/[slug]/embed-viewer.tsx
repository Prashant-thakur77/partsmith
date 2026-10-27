"use client";

import { ExternalLink } from "lucide-react";
import { PartStatusBadge } from "@/components/registry/part-status";
import { CadViewer } from "@/components/viewer/cad-viewer";
import { artifactUrl } from "@/lib/api";
import type { PartRecord } from "@/lib/api-types";

export function EmbedViewer({ slug, part }: { slug: string; part: PartRecord | null }) {
  return (
    <div className="flex h-dvh flex-col bg-surface">
      <CadViewer
        viewUrl={part?.artifacts.view}
        poster={artifactUrl(part?.thumbnail_url)}
        poster2x={artifactUrl(part?.thumbnail_2x_url)}
        className="min-h-0 flex-1"
        label={part ? `3D model of ${part.title}` : "3D model"}
        emptyText={part ? "No model yet." : "This part could not be loaded."}
      />
      <div className="flex items-center justify-between gap-2 border-t border-border px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-[13px] font-medium">{part?.title ?? slug}</span>
          {part ? <PartStatusBadge status={part.status} maxErrorMm={part.verification?.max_error_mm} /> : null}
        </div>
        <a href={`/parts/${encodeURIComponent(slug)}`} target="_blank" rel="noreferrer" className="inline-flex shrink-0 items-center gap-1 text-[12px] font-medium text-accent-text hover:underline">
          PartSmith <ExternalLink className="size-3" aria-hidden />
        </a>
      </div>
    </div>
  );
}
