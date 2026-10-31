"use client";

/**
 * "Print it": the files, the slicer settings the backend computed from the mesh (orientation, supports) next to the
 * suggested defaults (layer, walls, infill), grams and time (estimates, with how they are computed), the fit-test
 * coupon, and print shops near a city from the cited lookup (`POST /print-shops`: a place only renders with its link).
 */
import { useMutation } from "@tanstack/react-query";
import { Box, Download, ExternalLink, Info, Layers, MapPin, Ruler, Search } from "lucide-react";
import * as React from "react";
import { productApi, type PrintPlan, type PrintShops } from "@/lib/api-product";
import { citedPlaces, cityParam } from "@/lib/buy-or-print";
import { useCapabilities } from "@/lib/capabilities";
import { noteCouponDownload } from "@/lib/coupon-fit";
import { fmtNum } from "@/lib/format";
import { minutesText } from "@/lib/playground";
import { cn } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { ErrorState } from "../ui/error-state";
import { Input, Label } from "../ui/input";
import { ModeBadge } from "../ui/provenance";
import { Spinner } from "../ui/spinner";
import { Tooltip } from "../ui/tooltip";
import { LoadNoteBox } from "./load-note";

const PLACE_KIND: Record<string, string> = { print_shop: "print shop", repair_cafe: "repair café", maker_space: "maker space", other: "place" };

function Note({ text, label }: { text?: string; label: string }) {
  if (!text) return null;
  return (
    <Tooltip content={text}>
      <span tabIndex={0} role="img" aria-label={`How ${label} is worked out`} className="inline-flex cursor-help text-subtle hover:text-fg">
        <Info className="size-3.5" aria-hidden />
      </span>
    </Tooltip>
  );
}

function Row({ label, note, children }: { label: string; note?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-border py-1.5 last:border-b-0">
      <dt className="inline-flex items-center gap-1 text-[12.5px] text-muted">
        {label} <Note text={note} label={label.toLowerCase()} />
      </dt>
      <dd className="text-right text-[12.5px] text-fg">{children}</dd>
    </div>
  );
}

function Shops({ title }: { title: string }) {
  const id = React.useId();
  const [city, setCity] = React.useState("");
  const q = useMutation({ mutationFn: (c: string) => productApi.printShops(c, title) });
  const places = citedPlaces(q.data as PrintShops | undefined);
  return (
    <div className="space-y-2 border-t border-border pt-3">
      <h3 className="flex items-center gap-1.5 text-[13px] font-semibold">
        <MapPin className="size-3.5 text-muted" aria-hidden /> Find a print shop near you
      </h3>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const c = cityParam(city);
          if (c && c.length >= 2) q.mutate(c);
        }}
      >
        <Label htmlFor={id} className="sr-only">
          Your city
        </Label>
        <Input id={id} value={city} onChange={(e) => setCity(e.target.value)} placeholder="Your city, e.g. Pune" autoComplete="address-level2" maxLength={80} className="h-8 text-[13px]" />
        <Button type="submit" size="sm" variant="outline" disabled={q.isPending || (cityParam(city)?.length ?? 0) < 2}>
          {q.isPending ? <Spinner label="Searching" /> : <Search aria-hidden />} Search
        </Button>
      </form>
      <p className="text-[11px] text-subtle">A web search with citations: a place is listed only with the page it came from. Your city is sent to the search.</p>
      {q.isError ? <ErrorState error={q.error} compact what="the print-shop search" /> : null}
      {q.data ? (
        <div className="space-y-1.5" aria-live="polite">
          <div className="flex flex-wrap items-center gap-1.5">
            <ModeBadge mode={q.data.mode} />
            {q.data.cached ? <Badge tone="neutral">saved answer</Badge> : null}
          </div>
          {places.length ? (
            <ul className="space-y-1.5 text-[12.5px]">
              {places.map((p) => (
                <li key={p.href + p.name} className="space-y-0.5">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <a href={p.href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-accent-text underline-offset-2 hover:underline">
                      {p.name} <ExternalLink className="size-3" aria-hidden />
                      <span className="sr-only">(opens in a new tab)</span>
                    </a>
                    <span className="text-[11px] text-subtle">{PLACE_KIND[p.kind] ?? p.kind}</span>
                  </div>
                  {p.quote ? <q className="line-clamp-2 block text-[11.5px] text-subtle italic">{p.quote}</q> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[12px] text-muted">
              {q.data.mode === "mock" ? "No web search ran (no search key on this server), so no shop is listed." : `No cited print shop found near ${q.data.city ?? "that city"}.`}
            </p>
          )}
          {q.data.label && q.data.mode !== "mock" ? <p className="text-[11px] text-subtle">{q.data.label}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

/** One panel for every place a part can be printed from: a Describe result, the playground, a job, a part. */
export function PrintItPanel({
  plan,
  title,
  stlUrl,
  threemfUrl,
  couponUrl,
  disabled = false,
  note,
  className,
  headingLevel = "h2",
  family,
  fileNames,
}: {
  plan: PrintPlan | null | undefined;
  title: string;
  stlUrl?: string;
  threemfUrl?: string;
  couponUrl?: string | null;
  /** Downloads locked (e.g. waiting for the export-gate acknowledgement). */
  disabled?: boolean;
  /** One plain line above the files (e.g. "Not checked against a real part"). */
  note?: React.ReactNode;
  className?: string;
  headingLevel?: "h2" | "h3";
  /** The part's family: load-bearing families get a material and load note. */
  family?: string | null;
  /** `download` names for the files (the same names the server sends). */
  fileNames?: { stl?: string; threemf?: string };
}) {
  const caps = useCapabilities();
  const H = headingLevel;
  const pla = plan?.estimates.find((e) => e.material === "PLA") ?? plan?.estimates[0];
  const file = (href: string | undefined, label: string, sub: string, Icon: typeof Box, name?: string) =>
    href ? (
      <a
        href={disabled ? undefined : href}
        aria-disabled={disabled || undefined}
        tabIndex={disabled ? -1 : undefined}
        download={name ?? true}
        className={cn(
          "flex items-center gap-2.5 rounded-md border border-border px-3 py-2 text-[13px] transition-colors hover:border-border-strong hover:bg-surface-2",
          disabled && "pointer-events-none opacity-45",
        )}
      >
        <Icon className="size-4 text-muted" aria-hidden />
        <span className="flex-1">
          <span className="font-medium">{label}</span> <span className="text-subtle">· {sub}</span>
        </span>
        <Download className="size-3.5 text-subtle" aria-hidden />
      </a>
    ) : null;

  return (
    <section className={cn("space-y-3 rounded-lg border border-border bg-surface p-4", className)} aria-label="Print it">
      <div className="flex items-center justify-between gap-2">
        <H className="text-[14px] font-semibold tracking-tight">Print it</H>
        <Badge tone="outline">from the mesh</Badge>
      </div>
      {note ? <div className="text-[12.5px] text-muted">{note}</div> : null}
      <div className="grid gap-1.5 sm:grid-cols-2">
        {file(stlUrl, "STL", "any slicer", Box, fileNames?.stl)}
        {file(threemfUrl, "3MF", "with print settings", Layers, fileNames?.threemf)}
      </div>
      {plan ? (
        <dl>
          <Row label="Orientation" note={plan.notes.orientation}>
            {plan.orientation.replace(/^[+-][XYZ]:\s*/, "")}
          </Row>
          <Row label="Supports" note={plan.notes.supports_needed}>
            {plan.supports_needed ? "needed" : "not needed"}
          </Row>
          <Row label="Layer · walls · infill" note={plan.notes.settings}>
            <span className="font-mono tnum">
              {fmtNum(plan.layer_mm, 2)} mm · {plan.walls} · {plan.infill_percent} %
            </span>{" "}
            <Badge tone="neutral">suggested</Badge>
          </Row>
          <Row label="Nozzle · material" note={plan.notes.settings}>
            <span className="font-mono tnum">{fmtNum(plan.nozzle_mm, 1)} mm</span> · {plan.material}
          </Row>
          {pla ? (
            <>
              <Row label="Filament (upper bound)" note={plan.notes.grams}>
                <span className="font-mono tnum">{fmtNum(pla.grams, pla.grams < 10 ? 2 : 1)} g</span> <span className="text-muted">{pla.material}</span>
              </Row>
              {pla.print_minutes != null ? (
                <Row label="Print time (estimate)" note={plan.notes.minutes}>
                  <span className="font-mono tnum">{minutesText(pla.print_minutes)}</span>
                </Row>
              ) : null}
            </>
          ) : null}
        </dl>
      ) : (
        <p className="text-[12px] text-muted">Print settings appear once the part has been baked.</p>
      )}
      {couponUrl ? (
        <a href={couponUrl} download onClick={noteCouponDownload} className="flex items-center gap-2 rounded-md border border-border bg-surface-2 px-3 py-2 text-[12.5px] hover:border-border-strong">
          <Ruler className="size-3.5 text-muted" aria-hidden />
          <span>
            <span className="font-medium">Fit-test coupon</span> <span className="text-muted">· print this small test first: it carries the holes at −0.2, 0 and +0.2 mm</span>
          </span>
        </a>
      ) : null}
      <LoadNoteBox family={family} />
      {caps.has("post", "/print-shops") ? <Shops title={title} /> : null}
    </section>
  );
}
