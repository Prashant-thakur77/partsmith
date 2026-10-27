import { Layers, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { artifactUrl } from "@/lib/api";
import type { PartCard as PartCardT } from "@/lib/api-types";
import { titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";
import { OriginBadge } from "../ui/provenance";
import { PartStatusBadge } from "./part-status";

export function PartThumb({ url, url2x, title, className }: { url?: string | null; url2x?: string | null; title: string; className?: string }) {
  const src = artifactUrl(url);
  const src2 = artifactUrl(url2x);
  return (
    <div className={cn("relative aspect-[4/3] overflow-hidden bg-[var(--viewer-bg)] bg-dots", className)}>
      {src ? (
        // eslint-disable-next-line @next/next/no-img-element -- thumbnails are API artifacts of unknown size
        <img
          src={src}
          srcSet={src2 ? `${src} 1x, ${src2} 2x` : undefined}
          alt={`Render of ${title}`}
          loading="lazy"
          decoding="async"
          className="absolute inset-0 size-full object-contain p-3"
        />
      ) : (
        <div className="absolute inset-0 flex items-center justify-center">
          <svg viewBox="0 0 80 60" className="h-1/2 text-border-strong" aria-hidden>
            <path d="M10 45 L40 52 L70 40 L70 22 L40 14 L10 26 Z M10 26 L40 34 L70 22 M40 34 L40 52" fill="none" stroke="currentColor" strokeWidth="1.2" />
          </svg>
          <span className="sr-only">No render yet</span>
        </div>
      )}
    </div>
  );
}

export function PartCard({ part, className }: { part: PartCardT; className?: string }) {
  return (
    <Link
      href={`/parts/${encodeURIComponent(part.slug)}`}
      className={cn(
        "group flex flex-col overflow-hidden rounded-lg border border-border bg-surface shadow-sm transition-[border-color,box-shadow,transform] hover:-translate-y-0.5 hover:border-border-strong hover:shadow-md",
        className,
      )}
    >
      <PartThumb url={part.thumbnail_url} url2x={part.thumbnail_2x_url} title={part.title} className="border-b border-border" />
      <div className="flex flex-1 flex-col gap-2.5 p-3.5">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="line-clamp-2 text-[14px] leading-5 font-medium text-fg group-hover:text-accent-text" title={part.title}>
              {part.title}
            </h3>
            <p className="truncate text-[12px] text-muted">{titleCase(part.family)}</p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <PartStatusBadge status={part.status} maxErrorMm={part.max_error_mm} />
          <OriginBadge origin={part.origin} hideReal />
        </div>
        {part.reason ? <p className="line-clamp-2 text-[12px] leading-4 text-muted">{part.reason}</p> : null}
        <div className="mt-auto flex items-center gap-3 pt-1 text-[12px] text-subtle">
          <span className="inline-flex items-center gap-1">
            <SlidersHorizontal className="size-3.5" aria-hidden />
            <span className="font-mono tnum">{part.params_count}</span> knobs
          </span>
          {part.topology_knobs.length ? (
            <span className="inline-flex min-w-0 items-center gap-1">
              <Layers className="size-3.5 shrink-0" aria-hidden />
              <span className="truncate font-mono">{part.topology_knobs.join(", ")}</span>
            </span>
          ) : null}
        </div>
      </div>
    </Link>
  );
}

export function PartCardSkeleton() {
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface">
      <div className="skeleton aspect-[4/3]" />
      <div className="space-y-2 p-3.5">
        <div className="skeleton h-4 w-2/3 rounded" />
        <div className="skeleton h-3 w-1/3 rounded" />
        <div className="skeleton h-5 w-1/2 rounded" />
      </div>
    </div>
  );
}
