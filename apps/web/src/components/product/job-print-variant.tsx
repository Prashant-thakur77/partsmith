"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import * as React from "react";
import { ExportGateNotice, useExportGate } from "@/components/export-gate";
import { api, artifactUrl } from "@/lib/api";
import { PRODUCT, productApi } from "@/lib/api-product";
import type { ParamSpec, Verification } from "@/lib/api-types";
import { useCapabilities } from "@/lib/capabilities";
import { withAck } from "@/lib/ship";
import { cn } from "@/lib/utils";
import { PrintItPanel } from "./print-it-panel";
import { VariantMaker } from "./variant-maker";

/**
 * A finished job's "Print it" and "Make a variant", side by side. Verified jobs open in one click; best-effort jobs
 * show the export gate's reason and need the acknowledgement first (the server re-checks every download); failed
 * jobs show nothing here.
 */
export function JobPrintAndVariant({
  jobId,
  title,
  verification,
  artifacts,
  params,
  values,
  base,
  slug,
  family,
  knobsHref,
  className,
}: {
  jobId: string;
  title: string;
  verification: Verification | null;
  artifacts: Record<string, string>;
  params: ParamSpec[];
  values: Record<string, number>;
  base: Record<string, number>;
  slug: string | null;
  /** The part's family (load-bearing families get a material and load note). */
  family?: string | null;
  /** Anchor of the knob panel on the page, linked from the empty "Make a variant" state. */
  knobsHref?: string;
  className?: string;
}) {
  const caps = useCapabilities();
  const gate = useExportGate(verification);
  const plan = useQuery({
    queryKey: ["job-print-plan", jobId],
    queryFn: () => productApi.jobPrintPlan(jobId),
    enabled: caps.has("get", PRODUCT.jobPrintPlan) && !gate.blocked,
    staleTime: 60_000,
    retry: false,
  });
  if (gate.blocked || !params.length) return null;
  const acked = gate.state === "best_effort" && gate.ack;
  return (
    <div className={cn("grid grid-cols-1 gap-4 lg:grid-cols-2", className)}>
      <div className="space-y-3">
        {gate.locked && !gate.ack ? <ExportGateNotice verification={verification} couponUrl={artifactUrl(artifacts.coupon)} ack={gate.ack} onAck={gate.setAck} /> : null}
        <PrintItPanel
          plan={plan.data?.print_plan}
          title={title}
          stlUrl={withAck(artifactUrl(artifacts.stl), acked)}
          threemfUrl={withAck(artifactUrl(artifacts.threemf), acked)}
          couponUrl={artifactUrl(artifacts.coupon)}
          disabled={!gate.open}
          family={family}
          note={verification?.verified ? "Settings for the verified model as it was checked (the job's own knob values)." : "Best effort: print the fit-test coupon first."}
        />
      </div>
      <div className="rounded-lg border border-border bg-surface p-4">
        <VariantMaker
          slug={slug}
          params={params}
          values={values}
          base={base}
          verified={!!verification?.verified}
          downloadUrl={(f) => (gate.open ? withAck(api.jobBakeDownloadUrl(jobId, values, f), acked) : undefined)}
          lockedNote="Acknowledge the export notice on the left first."
          knobsHref={knobsHref}
        />
        {!slug ? (
          <p className="mt-3 text-[12px] text-subtle">Publish the job to save variants of it in the registry.</p>
        ) : (
          <p className="mt-3 text-[12px] text-subtle">
            Published as{" "}
            <Link href={`/parts/${encodeURIComponent(slug)}`} className="font-mono text-accent-text hover:underline">
              {slug}
            </Link>
            : its page also takes a variant in plain words (“2 mm taller”).
          </p>
        )}
      </div>
    </div>
  );
}
