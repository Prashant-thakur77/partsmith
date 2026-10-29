"use client";

/**
 * /p/{id}: a printed repair passport. What the part is, how it was verified, and "Reprint": the passport's own bake
 * route through the export gate, with the fit preset picked here and, when this device has reported a fit-test
 * coupon, the clearance it learned (`fit_session`). "It broke in a new place" starts a fix with the family and an
 * intent prefilled. Every number comes from the API.
 */
import { ArrowRight, Download, Lock, Printer, QrCode, Search, Wrench } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { learnedLabel, useLearnedClearances, useRememberedPreset } from "@/components/jobs/coupon-fit";
import { usePresets } from "@/components/jobs/fit-presets";
import { PassportShare } from "@/components/passport/passport-share";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, Select } from "@/components/ui/input";
import { OriginBadge } from "@/components/ui/provenance";
import type { Passport } from "@/lib/api-types";
import { fmtMm, titleCase } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { groupPassportId, normalizePassportId, reprintOpen, reprintUrl, type ReprintFormat } from "@/lib/passport";

const STATUS: Record<Passport["status"], { label: string; tone: "ok" | "warn" | "bad" | "neutral" }> = {
  verified: { label: "Verified", tone: "ok" },
  best_effort: { label: "Best effort · not verified", tone: "warn" },
  failed: { label: "Failed verification", tone: "bad" },
  unknown: { label: "No verification record", tone: "neutral" },
};

const FORMATS: { v: ReprintFormat; label: string }[] = [
  { v: "3mf", label: "3MF (slicer project)" },
  { v: "stl", label: "STL (mesh)" },
  { v: "step", label: "STEP (CAD)" },
];

function Reprint({ passport }: { passport: Passport }) {
  const { t } = useT();
  const presets = usePresets();
  const learned = useLearnedClearances();
  // The preset this device last chose (its printer) wins over the one stated for the original part.
  const [stored, setStored] = useRememberedPreset();
  const preset = stored || passport.preset.id;
  const [format, setFormat] = React.useState<ReprintFormat>("3mf");
  const [mark, setMark] = React.useState(false);
  const [ack, setAck] = React.useState(false);
  const ship = passport.ship.status;
  const open = reprintOpen(ship, ack);
  const lc = learned.byId.get(preset);
  const list = presets.data ?? [];
  const chosen = list.find((p) => p.id === preset);
  const href = reprintUrl(passport.bake_url, { format, preset, fitSession: lc?.source === "learned" ? learned.session : null, ack: ship === "best_effort" && ack, mark });
  const ids = { preset: React.useId(), format: React.useId(), mark: React.useId(), ack: React.useId() };
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Printer className="size-4 text-muted" aria-hidden /> Reprint
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-[13px] leading-6 text-muted">
          The same model{passport.superseded ? " (this id was issued for an earlier version of the same geometry)" : ""}, at the knob values below. The
          fit preset adds its clearance to holes, bores and gaps only; outer sizes never change.
        </p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="min-w-0 space-y-1.5">
            <Label htmlFor={ids.preset}>Printer and material</Label>
            <Select
              id={ids.preset}
              className="w-full"
              value={preset}
              onChange={(e) => setStored(e.target.value)}
            >
              {list.length ? (
                list.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title}
                  </option>
                ))
              ) : (
                <option value={passport.preset.id}>{passport.preset.title}</option>
              )}
            </Select>
            <p className="text-[12px] leading-5 text-subtle">
              Clearance <span className="font-mono text-fg tnum">{fmtMm(lc ? lc.clearance_mm : (chosen?.delta_mm ?? passport.preset.delta_mm))}</span>
              {" · "}
              {lc ? learnedLabel(lc, t) : "documented starting point"}
              {preset === passport.preset.id && passport.preset.source === "job_spec" ? " · the material and printer stated for this part" : ""}
            </p>
          </div>
          <div className="min-w-0 space-y-1.5">
            <Label htmlFor={ids.format}>File</Label>
            <Select id={ids.format} className="w-full" value={format} onChange={(e) => setFormat(e.target.value as ReprintFormat)}>
              {FORMATS.map((f) => (
                <option key={f.v} value={f.v}>
                  {f.label}
                </option>
              ))}
            </Select>
          </div>
        </div>
        <label htmlFor={ids.mark} className="flex cursor-pointer items-start gap-2 text-[13px] text-fg">
          <input id={ids.mark} type="checkbox" checked={mark} onChange={(e) => setMark(e.target.checked)} className="mt-0.5 size-4 accent-[var(--accent)]" />
          <span>
            Emboss the passport id on the part
            <span className="block text-[12px] text-muted">
              0.4 mm deep on an upward face that touches nothing measured; skipped (and the file says so) when the part has no 25 × 8 mm free area.
            </span>
          </span>
        </label>
        {ship !== "verified" ? (
          <div className="space-y-2 rounded-lg border border-warn-border bg-warn-soft p-3 text-[13px]" role="note">
            <p className="flex items-start gap-2 text-fg">
              <Lock className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
              <span>{passport.ship.reason}</span>
            </p>
            {ship === "best_effort" ? (
              <label htmlFor={ids.ack} className="flex cursor-pointer items-start gap-2 text-[12.5px] text-fg">
                <input id={ids.ack} type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-0.5 size-4 accent-[var(--accent)]" />
                {t("gate.ack")}
              </label>
            ) : null}
          </div>
        ) : null}
        {open ? (
          <Button asChild variant="primary" className="w-full sm:w-auto">
            <a href={href} download>
              <Download aria-hidden /> Download {format.toUpperCase()}
            </a>
          </Button>
        ) : (
          <Button variant="outline" disabled className="w-full sm:w-auto">
            <Lock aria-hidden /> {ship === "blocked" ? "No download: it failed verification" : "Acknowledge to download"}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

export function PassportClient({ passport }: { passport: Passport }) {
  const st = STATUS[passport.status];
  const values = Object.entries(passport.values);
  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <p className="flex items-center gap-1.5 text-[12px] font-medium tracking-[0.08em] text-accent-text uppercase">
          <QrCode className="size-3.5" aria-hidden /> Repair passport <span className="font-mono">{groupPassportId(passport.id)}</span>
        </p>
        <h1 className="text-[26px] leading-tight font-semibold tracking-[-0.025em] break-words sm:text-[30px]">{passport.title}</h1>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={st.tone}>{st.label}</Badge>
          <OriginBadge origin={passport.origin} />
          <Badge tone="outline">{titleCase(passport.family)}</Badge>
          {passport.version != null ? (
            <Badge tone="outline" className="font-mono">
              v{passport.version}
              {passport.superseded && passport.current_version != null ? ` → v${passport.current_version}` : ""}
            </Badge>
          ) : null}
        </div>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-6">
          <Reprint passport={passport} />
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Wrench className="size-4 text-muted" aria-hidden /> It broke in a new place?
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-[13px] leading-6 text-muted">A new break needs new photos: the reprint above is the part as it was verified, not the new damage.</p>
              <Button asChild variant="outline">
                <Link href={passport.fix_url}>
                  Start a fix <ArrowRight aria-hidden />
                </Link>
              </Button>
            </CardContent>
          </Card>
        </div>

        <div className="min-w-0 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Verification</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-[13px] leading-6 text-muted">
              <p>
                {st.label}
                {passport.max_error_mm != null ? (
                  <>
                    {" "}at <span className="font-mono text-fg tnum">{fmtMm(passport.max_error_mm)}</span> max error vs the photo
                    {passport.threshold_mm != null ? <> (limit <span className="font-mono tnum">{fmtMm(passport.threshold_mm)}</span>)</> : null}
                  </>
                ) : null}
                .
              </p>
              {passport.slug ? (
                <Link href={passport.page_url} className="inline-flex items-center gap-1 font-medium text-accent-text hover:underline">
                  Open the part page <ArrowRight className="size-3.5" aria-hidden />
                </Link>
              ) : null}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Knob values</CardTitle>
            </CardHeader>
            <CardContent>
              {values.length ? (
                <dl className="divide-y divide-border text-[13px]">
                  {values.map(([k, v]) => (
                    <div key={k} className="flex items-baseline justify-between gap-3 py-1.5">
                      <dt className="min-w-0 truncate text-muted">{k.replaceAll("_", " ")}</dt>
                      <dd className="font-mono text-fg tnum">{Number.isInteger(v) ? v : v.toFixed(2)}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p className="text-[13px] text-muted">This part has no knobs.</p>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <PassportShare passport={{ id: passport.id, url: passport.url, qr_svg_url: passport.qr_svg_url, qr_png_url: passport.qr_png_url }} title={passport.title} />
            </CardContent>
          </Card>
          {passport.notes.length ? (
            <ul className="list-disc space-y-1 pl-4 text-[12px] leading-5 text-muted">
              {passport.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/** Unknown or mistyped id: the closest ids the server knows, and a box to type it again. */
export function PassportNotFound({ id, message, closest }: { id: string; message: string | null; closest: string[] }) {
  const router = useRouter();
  const [value, setValue] = React.useState(id);
  const pid = normalizePassportId(value);
  const inputId = React.useId();
  return (
    <div className="mx-auto max-w-lg space-y-5">
      <h1 className="text-[24px] font-semibold tracking-[-0.02em]">{message ? "No part with this passport" : "The registry is not reachable"}</h1>
      <p className="text-[14px] leading-6 text-muted">
        {message ?? "Try again in a moment."} Passport ids are 6 letters or digits, printed on the part and on its repair card.
      </p>
      {closest.length ? (
        <div className="space-y-1.5">
          <p className="text-[13px] font-medium text-fg">Did you mean</p>
          <ul className="flex flex-wrap gap-2">
            {closest.map((c) => (
              <li key={c}>
                <Link href={`/p/${encodeURIComponent(c)}`} className="inline-flex rounded-md border border-border px-2.5 py-1 font-mono text-[14px] tracking-[0.08em] hover:border-border-strong">
                  {groupPassportId(c)}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (pid) router.push(`/p/${pid}`);
        }}
      >
        <Label htmlFor={inputId} className="sr-only">
          Passport id
        </Label>
        <Input id={inputId} value={value} onChange={(e) => setValue(e.target.value)} placeholder="7KQ 3MZ" autoCapitalize="characters" autoComplete="off" className="font-mono" />
        <Button type="submit" variant="outline" disabled={!pid} aria-label="Open passport">
          <Search aria-hidden />
        </Button>
      </form>
    </div>
  );
}
