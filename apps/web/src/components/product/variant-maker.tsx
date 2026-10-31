"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowUpRight, Box, Download, GitFork, Layers, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { useAdmin } from "@/components/admin-access";
import { PRODUCT, productApi } from "@/lib/api-product";
import type { ParamSpec } from "@/lib/api-types";
import { useCapabilities } from "@/lib/capabilities";
import { fmtNum, paramLabel } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { ErrorState } from "../ui/error-state";
import { Input, Label } from "../ui/input";
import { Spinner } from "../ui/spinner";

/** The knobs that differ from `base` (the part's own values), in PARAMS order. */
export function variantChanges(params: ParamSpec[], values: Record<string, number>, base: Record<string, number>) {
  return params
    .filter((p) => values[p.name] !== undefined && Math.abs(values[p.name]! - (base[p.name] ?? p.default)) > Math.max(p.step / 2, 1e-9))
    .map((p) => ({ spec: p, from: base[p.name] ?? p.default, to: values[p.name]! }));
}

/**
 * "Make a variant": the knobs above at new values become their own registry part (admin: `POST /parts/{slug}/variants`,
 * best effort with the reason "a variant of a verified part, not itself checked against a photo"), or, for everyone
 * else, the files at those values. The parent's photo check never carries over to the variant.
 */
export function VariantMaker({
  slug,
  params,
  values,
  base,
  verified,
  downloadUrl,
  lockedNote,
  knobsHref,
  className,
}: {
  /** Registry part to save the variant under (null: the job is not published, so only downloads are offered). */
  slug: string | null;
  params: ParamSpec[];
  values: Record<string, number>;
  base: Record<string, number>;
  verified: boolean;
  /** File link at the current values; undefined while the export gate is locked. */
  downloadUrl: (format: "stl" | "3mf" | "step") => string | undefined;
  lockedNote?: string;
  /** Where the knobs are on this page; the empty state links there and lists them. */
  knobsHref?: string;
  className?: string;
}) {
  const caps = useCapabilities();
  const { admin } = useAdmin();
  const titleId = React.useId();
  const [title, setTitle] = React.useState("");
  const changes = variantChanges(params, values, base);
  const canSave = !!slug && admin && caps.has("post", PRODUCT.variants);
  const save = useMutation({ mutationFn: () => productApi.saveVariant(slug!, Object.fromEntries(changes.map((c) => [c.spec.name, c.to])), title.trim() || undefined) });
  const key = JSON.stringify(changes.map((c) => [c.spec.name, c.to]));
  React.useEffect(() => save.reset(), [key]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <section className={cn("space-y-3", className)} aria-labelledby={`${titleId}-h`}>
      <div className="flex items-center justify-between gap-2">
        <h2 id={`${titleId}-h`} className="flex items-center gap-1.5 text-[14px] font-semibold tracking-tight">
          <GitFork className="size-4 text-muted" aria-hidden /> Make a variant
        </h2>
        {changes.length ? <Badge tone="accent">{changes.length} knob{changes.length === 1 ? "" : "s"} changed</Badge> : null}
      </div>
      {!changes.length ? (
        <div className="space-y-2">
          <p className="text-[13px] text-muted">
            No knob changed yet, so there is no variant to save. Move a knob, then save the result as its own part or download it at those values.
          </p>
          {knobsHref && params.length ? (
            <>
              <p className="text-[12px] text-subtle">
                {params.length} knob{params.length === 1 ? "" : "s"} on this part: {params.slice(0, 6).map((p) => paramLabel(p.name, p.label).toLowerCase()).join(", ")}
                {params.length > 6 ? ", …" : ""}
              </p>
              <Button asChild size="sm" variant="outline">
                <a href={knobsHref}>
                  <SlidersHorizontal aria-hidden /> Go to the knobs
                </a>
              </Button>
            </>
          ) : null}
        </div>
      ) : (
        <>
          <ul className="flex flex-wrap gap-1.5" aria-label="Changed knobs">
            {changes.map((c) => (
              <li key={c.spec.name}>
                <Badge tone="neutral" className="font-mono tnum">
                  {paramLabel(c.spec.name, c.spec.label)}: {fmtNum(c.from, 2)} → {fmtNum(c.to, 2)} {c.spec.unit}
                </Badge>
              </li>
            ))}
          </ul>
          <p role="note" className="rounded-md border border-warn-border bg-warn-soft px-2.5 py-1.5 text-[12.5px] text-fg">
            {verified ? "A variant of a verified part, not itself checked against a photo." : "A variant of a best-effort part, not checked against a photo."} The changed sizes
            are what you set, not what was measured.
          </p>
          {canSave ? (
            save.data ? (
              <div className="space-y-1.5 rounded-md border border-ok-border bg-ok-soft px-3 py-2 text-[13px]" aria-live="polite">
                <p className="font-medium text-fg">
                  Saved as <span className="font-mono">{save.data.slug}</span> <Badge tone="neutral">{save.data.action}</Badge>
                </p>
                <Link href={`/parts/${encodeURIComponent(save.data.slug)}`} className="inline-flex items-center gap-1 font-medium text-accent-text hover:underline">
                  Open the variant <ArrowUpRight className="size-3.5" aria-hidden />
                </Link>
              </div>
            ) : (
              <form
                className="space-y-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  save.mutate();
                }}
              >
                <Label htmlFor={titleId} className="text-[12px] text-muted">
                  Name (optional)
                </Label>
                <Input id={titleId} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} placeholder="e.g. Cable clip for a 6 mm cable" className="h-8 text-[13px]" />
                <Button type="submit" size="sm" variant="primary" disabled={save.isPending}>
                  {save.isPending ? <Spinner className="text-accent-fg" label="Saving" /> : <GitFork aria-hidden />} Save as a variant
                </Button>
                {save.isError ? <ErrorState error={save.error} compact what="the variant" /> : null}
              </form>
            )
          ) : null}
          <div className="space-y-1.5">
            <p className="text-[12px] text-subtle">{canSave ? "Or download it at these values:" : slug ? "Saving variants to the registry is for admins; anyone can download them:" : "Download it at these values:"}</p>
            {downloadUrl("stl") ? (
              <div className="grid grid-cols-3 gap-1.5">
                {(
                  [
                    { f: "stl", label: "STL", icon: Box },
                    { f: "3mf", label: "3MF", icon: Layers },
                    { f: "step", label: "STEP", icon: Box },
                  ] as const
                ).map((d) => (
                  <Button key={d.f} asChild size="sm" variant="outline">
                    <a href={downloadUrl(d.f)} download>
                      <Download aria-hidden /> {d.label}
                    </a>
                  </Button>
                ))}
              </div>
            ) : (
              <p className="text-[12px] text-muted">{lockedNote ?? "Acknowledge the export notice first."}</p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
