"use client";

/**
 * "Buy or print?" card for a job (`/jobs/{id}/buy-or-print`) or a published part (`/parts/{slug}/buy-or-print`).
 * Print side: code's numbers from the mesh, labelled estimates with their assumptions. Buy side: only what the lookup
 * kept with a cited page and quote; a price, a place or a part name never renders without its link. Items code dropped
 * are listed in a disclosure. A job without a stored lookup gets a "Look up prices" button (POST); a part never starts a
 * search. Nothing renders when the backend has no such route or answers 404/409.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Search } from "lucide-react";
import * as React from "react";
import { ApiError, api } from "@/lib/api";
import type { BuyOrPrint } from "@/lib/api-types";
import { cardMode, citedOem, citedOffers, citedPlaces, cityParam, costEntries, hostOf, lookupState, money } from "@/lib/buy-or-print";
import { useCapabilities } from "@/lib/capabilities";
import { fmtNum } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { ErrorState } from "../ui/error-state";
import { Input, Label } from "../ui/input";
import { ModeBadge } from "../ui/provenance";
import { Spinner } from "../ui/spinner";

const PLACE_KIND: Record<string, string> = { print_shop: "print shop", repair_cafe: "repair café", maker_space: "maker space", other: "place" };

/** Shared query for the job card (the impact panel reads the same cache entry). */
export function useJobBuyOrPrint(jobId: string, finished: boolean) {
  const caps = useCapabilities();
  return useQuery({
    queryKey: ["job-buy-or-print", jobId],
    enabled: finished && caps.has("get", "/jobs/{id}/buy-or-print"),
    staleTime: 60_000,
    retry: false,
    queryFn: () => api.jobBuyOrPrint(jobId),
  });
}

function SourceLink({ href, label, className }: { href: string; label: React.ReactNode; className?: string }) {
  const { t } = useT();
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={cn("inline-flex min-w-0 items-center gap-1 text-accent-text underline-offset-2 hover:underline", className)}
    >
      <span className="truncate">{label}</span>
      <ExternalLink className="size-3 shrink-0" aria-hidden />
      <span className="sr-only">{t("bop.opens")}</span>
    </a>
  );
}

function Quote({ text }: { text: string }) {
  if (!text.trim()) return null;
  return <q className="line-clamp-2 block text-[11.5px] text-subtle italic">{text}</q>;
}

function CardBody({
  card,
  onLookup,
  lookupPending,
  lookupError,
}: {
  card: BuyOrPrint;
  onLookup?: (city: string | null) => void;
  lookupPending?: boolean;
  lookupError?: unknown;
}) {
  const { t } = useT();
  const cityId = React.useId();
  const [city, setCity] = React.useState("");
  const state = lookupState(card);
  // the MOCK badge and the "no web search ran" line already say it: drop the backend's own mock notes
  const notes = state === "mock" ? card.notes.filter((n) => !/^MOCK\b/.test(n)) : card.notes;
  const lookup = card.lookup ?? null;
  const offers = citedOffers(lookup);
  const places = citedPlaces(lookup);
  const oem = citedOem(lookup);
  const dropped = lookup?.dropped ?? [];

  return (
    <>
      {card.status === "best_effort" || card.status === "failed" ? (
        <p role="note" className={cn("rounded-md border px-2.5 py-1.5 text-[12px]", card.status === "failed" ? "border-bad-border bg-bad-soft" : "border-warn-border bg-warn-soft")}>
          {card.status === "failed" ? t("bop.statusFailed") : t("bop.statusBestEffort")}
        </p>
      ) : null}

      <div className="grid grid-cols-1 gap-4">
        {/* print side: code */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-[13px] font-semibold">{t("bop.print")}</h3>
            <Badge tone="outline">{t("bop.estimate")}</Badge>
          </div>
          {card.prints.length ? (
            <dl className="space-y-1.5 text-[12.5px]">
              {card.prints.map((p) => (
                <div key={p.material} className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 border-b border-border pb-1.5 last:border-0">
                  <dt className="font-medium">{p.material}</dt>
                  <dd className="text-right font-mono tnum">
                    <span>{fmtNum(p.grams, p.grams < 10 ? 2 : 1)} g</span>
                    {p.print_minutes != null ? <span className="text-muted"> · {fmtNum(p.print_minutes, 0)} min</span> : null}
                    {costEntries(p).map((c) => (
                      <span key={c.currency} className="text-muted">
                        {" "}
                        · {money(c.amount, c.currency)}
                      </span>
                    ))}
                  </dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="text-[12px] text-muted">No print estimate: the model has no mesh yet.</p>
          )}
          {card.prints.some((p) => p.assumptions.length) ? (
            <details className="text-[11.5px] text-subtle">
              <summary className="cursor-pointer rounded-sm select-none">{t("bop.assumptions")}</summary>
              <ul className="mt-1 list-disc space-y-0.5 pl-4">
                <li>grams = {t("bop.filament")}</li>
                {[...new Set(card.prints.flatMap((p) => p.assumptions))].map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>

        {/* buy side: cited only */}
        <div className="space-y-2 border-t border-border pt-3">
          <h3 className="text-[13px] font-semibold">{t("bop.buy")}</h3>
          {oem || offers.length ? <p className="text-[11.5px] text-muted">{t("bop.nameMatch")}</p> : null}

          {oem ? (
            <div className="space-y-0.5 text-[12.5px]">
              <div className="flex flex-wrap items-baseline gap-x-1.5">
                <span className="text-muted">{t("bop.oem")}:</span>
                <span className="font-medium">{oem.name}</span>
                {oem.number ? <span className="font-mono text-[11.5px] text-muted">{oem.number}</span> : null}
                <SourceLink href={oem.href} label={`${t("bop.source")}: ${hostOf(oem.href)}`} className="text-[11.5px]" />
              </div>
              <Quote text={oem.quote} />
            </div>
          ) : null}

          {offers.length ? (
            <ul className="space-y-2 text-[12.5px]" aria-label={t("bop.buy")}>
              {offers.map((o) => (
                <li key={`${o.href}|${o.price}|${o.currency}`} className="space-y-0.5">
                  {/* One link carries seller and price, so a price can never show without its source. */}
                  <a
                    href={o.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="group flex items-baseline justify-between gap-2 rounded-sm"
                  >
                    <span className="inline-flex min-w-0 items-center gap-1 text-accent-text underline-offset-2 group-hover:underline">
                      <span className="truncate">{o.seller}</span>
                      <ExternalLink className="size-3 shrink-0" aria-hidden />
                    </span>
                    <span className="shrink-0 font-mono text-fg tnum">{money(o.price, o.currency)}</span>
                    <span className="sr-only">{t("bop.opens")}</span>
                  </a>
                  {o.title || o.availability ? (
                    <p className="truncate text-[11.5px] text-muted">{[o.title, o.availability].filter(Boolean).join(" · ")}</p>
                  ) : null}
                  <Quote text={o.quote} />
                </li>
              ))}
            </ul>
          ) : state === "mock" ? (
            <p className="text-[12px] text-muted">{t("bop.mock")}</p>
          ) : state === "not_searched" ? (
            <p className="text-[12px] text-muted">{t("bop.notSearched")}</p>
          ) : state === "searched" ? (
            <p className="text-[12px] text-muted">{t("bop.noOffers")}</p>
          ) : (
            <p className="text-[12px] text-muted">{t("bop.noLookup")}</p>
          )}

          {state === "none" && onLookup ? (
            <form
              className="space-y-2 rounded-md border border-border bg-surface-2 p-2.5"
              onSubmit={(e) => {
                e.preventDefault();
                onLookup(cityParam(city));
              }}
            >
              <div className="space-y-1">
                <Label htmlFor={cityId} className="text-[12px]">
                  {t("bop.city")}
                </Label>
                <Input
                  id={cityId}
                  value={city}
                  maxLength={80}
                  autoComplete="address-level2"
                  onChange={(e) => setCity(e.target.value)}
                  aria-describedby={`${cityId}-hint`}
                  className="h-8 text-[13px]"
                />
                <p id={`${cityId}-hint`} className="text-[11px] text-subtle">
                  {t("bop.cityHint")}
                </p>
              </div>
              <Button type="submit" size="sm" variant="outline" disabled={lookupPending}>
                {lookupPending ? <Spinner label={t("bop.lookingUp")} /> : <Search aria-hidden />}
                {lookupPending ? t("bop.lookingUp") : t("bop.lookup")}
              </Button>
              {lookupError ? <ErrorState error={lookupError} compact what="the price lookup" className="py-3" /> : null}
            </form>
          ) : null}
        </div>

        {lookup?.city ? (
          <div className="space-y-1.5 border-t border-border pt-3">
            <h3 className="text-[13px] font-semibold">{t("bop.places", { city: lookup.city })}</h3>
            {places.length ? (
              <ul className="space-y-1.5 text-[12.5px]">
                {places.map((p) => (
                  <li key={p.href + p.name} className="space-y-0.5">
                    <div className="flex flex-wrap items-baseline gap-x-2">
                      <SourceLink href={p.href} label={p.name} />
                      <span className="text-[11px] text-subtle">{PLACE_KIND[p.kind] ?? p.kind}</span>
                    </div>
                    <Quote text={p.quote} />
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[12px] text-muted">{t("bop.noPlaces", { city: lookup.city })}</p>
            )}
          </div>
        ) : null}

        {dropped.length ? (
          <details className="border-t border-border pt-2 text-[11.5px] text-muted">
            <summary className="cursor-pointer rounded-sm select-none">
              {dropped.length === 1 ? t("bop.droppedOne") : t("bop.dropped", { n: dropped.length })}
            </summary>
            <ul className="mt-1 list-disc space-y-0.5 pl-4">
              {dropped.map((d, i) => (
                <li key={`${i}-${d}`}>{d}</li>
              ))}
            </ul>
          </details>
        ) : null}

        {(lookup?.label && state !== "mock") || notes.length || (lookup && lookup.mode !== "mock") ? (
          <div className="space-y-0.5 text-[11px] text-subtle">
            {lookup?.label && state !== "mock" ? <p>{lookup.label}</p> : null}
            {lookup && lookup.mode !== "mock" && (lookup.provider || lookup.model) ? (
              <p className="font-mono">
                {[lookup.provider, lookup.model].filter(Boolean).join(" · ")}
                {lookup.queries ? ` · ${lookup.queries} searches` : ""}
              </p>
            ) : null}
            {notes.map((n) => (
              <p key={n}>{n}</p>
            ))}
          </div>
        ) : null}
      </div>
    </>
  );
}

function Shell({ id, card, children }: { id: string; card: BuyOrPrint; children: React.ReactNode }) {
  const { t } = useT();
  return (
    <section className="space-y-3 rounded-lg border border-border bg-surface p-4" aria-labelledby={id}>
      <div className="flex items-center justify-between gap-2">
        <h2 id={id} className="text-[14px] font-semibold tracking-tight">
          {t("bop.title")}
        </h2>
        <ModeBadge mode={cardMode(card)} />
      </div>
      {children}
    </section>
  );
}

function quiet(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 404 || err.status === 409);
}

/** Job card: GET the stored card (or the print side), POST to look up prices when no lookup is stored. */
export function JobBuyOrPrintCard({ jobId, finished }: { jobId: string; finished: boolean }) {
  const caps = useCapabilities();
  const qc = useQueryClient();
  const q = useJobBuyOrPrint(jobId, finished);
  const lookup = useMutation({
    mutationFn: (city: string | null) => api.jobBuyOrPrintLookup(jobId, city),
    onSuccess: (card) => qc.setQueryData(["job-buy-or-print", jobId], card),
  });
  if (q.isError) return quiet(q.error) ? null : <ErrorState error={q.error} compact what="the buy-or-print card" />;
  if (!q.data) return null;
  return (
    <Shell id={`bop-${jobId}`} card={q.data}>
      <CardBody
        card={q.data}
        onLookup={caps.has("post", "/jobs/{id}/buy-or-print") ? (city) => lookup.mutate(city) : undefined}
        lookupPending={lookup.isPending}
        lookupError={lookup.error}
      />
    </Shell>
  );
}

/** Part card: shown only when `GET /parts/{slug}/buy-or-print` answers 200. Never starts a search. */
export function PartBuyOrPrintCard({ slug, className }: { slug: string; className?: string }) {
  const caps = useCapabilities();
  const q = useQuery({
    queryKey: ["part-buy-or-print", slug],
    enabled: caps.has("get", "/parts/{slug}/buy-or-print"),
    staleTime: 60_000,
    retry: false,
    queryFn: () => api.partBuyOrPrint(slug),
  });
  if (!q.data) return null;
  return (
    <div className={className}>
      <Shell id={`bop-part-${slug}`} card={q.data}>
        <CardBody card={q.data} />
      </Shell>
    </div>
  );
}
