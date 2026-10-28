"use client";

/**
 * Impact panel for one job: minutes from upload to the first print file (event timestamps), filament grams and cost
 * (from the baked mesh volume; `GET /jobs/{id}/impact`), all labelled estimates. When the buy-or-print card exists
 * (`GET /jobs/{id}/buy-or-print` answers 200), its code-computed print side replaces the filament rows here and the
 * card renders below this panel (print side, cited offers and places, dropped items), so the page shows one set of
 * figures. No number here is typed by hand.
 */
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { api } from "@/lib/api";
import { money } from "@/lib/buy-or-print";
import { useCapabilities } from "@/lib/capabilities";
import { fmtNum } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Badge } from "../ui/badge";
import { Eyebrow } from "../ui/card";
import { JobBuyOrPrintCard, useJobBuyOrPrint } from "./buy-or-print-card";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border py-1.5 last:border-0">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right font-mono tnum">{children}</dd>
    </div>
  );
}

export function ImpactPanel({ jobId, finished }: { jobId: string; finished: boolean }) {
  const { t } = useT();
  const caps = useCapabilities();
  const impact = useQuery({
    queryKey: ["job-impact", jobId],
    enabled: finished && caps.has("get", "/jobs/{id}/impact"),
    staleTime: 60_000,
    queryFn: () => api.jobImpact(jobId),
  });
  const bop = useJobBuyOrPrint(jobId, finished);
  const d = impact.data;
  // The buy-or-print card shows the code-computed print side; this panel then keeps only the time to the file.
  const cardPrints = !!bop.data?.prints.length;
  const m = d?.minutes_to_file;

  return (
    <>
      {d ? (
        <section className="rounded-lg border border-border bg-surface p-4" aria-labelledby={`impact-${jobId}`}>
          <div className="mb-1 flex items-center justify-between gap-2">
            <Eyebrow id={`impact-${jobId}`}>{t("impact.title")}</Eyebrow>
            <Badge tone="outline">{t("impact.estimate")}</Badge>
          </div>
          <dl className="text-[13px]">
            <Row label={t("impact.minutes")}>
              {m ? (
                <>
                  {fmtNum(m.minutes, m.minutes < 10 ? 1 : 0)} min
                  {m.waited_for_answer ? <span className="block font-sans text-[11px] text-subtle">{t("impact.waited")}</span> : null}
                </>
              ) : (
                <span className="font-sans text-muted">{t("impact.noFile")}</span>
              )}
            </Row>
            {!cardPrints && d.filament ? (
              <Row label={`${t("impact.filament")} (${d.filament.material})`}>
                {fmtNum(d.filament.grams, d.filament.grams < 10 ? 2 : 1)} g
              </Row>
            ) : null}
            {!cardPrints && d.cost.length ? (
              <Row label={t("impact.cost")}>{d.cost.map((c) => money(c.amount, c.currency)).join(" · ")}</Row>
            ) : null}
            {!cardPrints && d.print_minutes_est != null ? <Row label={t("impact.printTime")}>{fmtNum(d.print_minutes_est, 0)} min</Row> : null}
          </dl>
          {cardPrints ? <p className="mt-1.5 text-[11.5px] text-subtle">{t("bop.seeBelow")}</p> : null}

          <details className="mt-2 text-[11.5px] text-subtle">
            <summary className="cursor-pointer select-none">{t("impact.how")}</summary>
            <ul className="mt-1 list-disc space-y-0.5 pl-4">
              {m ? <li>time = first {m.kind === "threemf" ? "3MF" : m.kind.toUpperCase()} file event − job created (event timestamps)</li> : null}
              {!cardPrints && d.filament ? <li>grams: {d.filament.source}</li> : null}
              {!cardPrints ? d.assumptions.map((a) => <li key={a}>{a}</li>) : null}
              {d.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </details>
        </section>
      ) : null}
      <JobBuyOrPrintCard jobId={jobId} finished={finished} />
    </>
  );
}
