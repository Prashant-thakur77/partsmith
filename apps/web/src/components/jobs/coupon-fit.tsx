"use client";

/**
 * "How did the coupon fit?" — after the fit-test coupon is downloaded on this device, the person says per mating
 * feature whether the real screw / pin / tab is tight, just right or loose (optionally barely / very). The server
 * (`POST /fit-reports/coupon`) turns that into a learned clearance for that printer + material on this device, inside
 * the preset's documented range; only the clearance knob changes, never a measured size. Fit presets then use it.
 * Shown only when the API offers the route.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ruler } from "lucide-react";
import * as React from "react";
import { api } from "@/lib/api";
import type { LearnedClearance } from "@/lib/api-types";
import { useCapabilities } from "@/lib/capabilities";
import {
  COUPON_EVENT,
  PRESET_KEY,
  couponDownloaded,
  deviceId,
  reportBody,
  type CouponAmount,
  type CouponFeature,
  type CouponFit,
} from "@/lib/coupon-fit";
import { fmtMm } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Button } from "../ui/button";
import { ErrorState } from "../ui/error-state";
import { Label, Select } from "../ui/input";

function storage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

function subscribe(cb: () => void): () => void {
  window.addEventListener(COUPON_EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(COUPON_EVENT, cb);
    window.removeEventListener("storage", cb);
  };
}

export function useCouponDownloaded(): boolean {
  return React.useSyncExternalStore(subscribe, () => couponDownloaded(storage()), () => false);
}

/** This browser's random device id (null on the server or when storage is blocked). */
export function useDeviceId(): string | null {
  const [id, setId] = React.useState<string | null>(null);
  React.useEffect(() => setId(deviceId(storage())), []);
  return id;
}

/** The preset last chosen on this device (shared by Fit presets and the coupon control). */
export function useRememberedPreset(): [string, (id: string) => void] {
  const [v, setV] = React.useState("");
  React.useEffect(() => {
    try {
      setV(storage()?.getItem(PRESET_KEY) ?? "");
    } catch {
      /* storage blocked */
    }
  }, []);
  const set = React.useCallback((id: string) => {
    setV(id);
    try {
      storage()?.setItem(PRESET_KEY, id);
    } catch {
      /* storage blocked */
    }
  }, []);
  return [v, set];
}

/** Learned (or documented) clearance per preset for this device; empty when the API has no coupon routes. */
export function useLearnedClearances() {
  const caps = useCapabilities();
  const session = useDeviceId();
  const q = useQuery({
    queryKey: ["coupon-learned", session],
    enabled: caps.has("get", "/fit-reports/coupon") && !!session,
    staleTime: 30_000,
    queryFn: () => api.couponLearned(session),
  });
  const byId = React.useMemo(() => new Map((q.data ?? []).map((l) => [l.preset, l])), [q.data]);
  return { byId, session, query: q };
}

export function learnedLabel(l: LearnedClearance, t: (k: string, v?: Record<string, string | number>) => string): string {
  if (l.source !== "learned") return t("coupon.documented");
  return l.reports === 1 ? t("coupon.learnedOne") : t("coupon.learnedFrom", { n: l.reports });
}

const FITS: { v: CouponFit; key: string }[] = [
  { v: "tight", key: "coupon.tight" },
  { v: "ok", key: "coupon.ok" },
  { v: "loose", key: "coupon.loose" },
];

type Answers = Record<string, { fit?: CouponFit; amount?: CouponAmount | null }>;

function FeatureRow({ f, value, onChange, name }: { f: CouponFeature; value: Answers[string] | undefined; onChange: (v: Answers[string]) => void; name: string }) {
  const { t } = useT();
  const amountId = `${name}-amount`;
  return (
    <fieldset className="space-y-1.5">
      <legend className="text-[12.5px] font-medium text-fg">{f.label}</legend>
      <div className="grid grid-cols-3 gap-1.5">
        {FITS.map((o) => (
          <label key={o.v} className="relative">
            <input
              type="radio"
              name={name}
              value={o.v}
              checked={value?.fit === o.v}
              onChange={() => onChange({ fit: o.v, amount: o.v === "ok" ? null : (value?.amount ?? null) })}
              className="peer sr-only"
            />
            <span className="flex h-8 cursor-pointer items-center justify-center rounded-md border border-border-strong bg-surface px-2 text-[12.5px] text-fg transition-colors peer-checked:border-inverse peer-checked:bg-inverse peer-checked:text-inverse-fg peer-focus-visible:ring-2 peer-focus-visible:ring-ring/40 hover:bg-surface-2">
              {t(o.key)}
            </span>
          </label>
        ))}
      </div>
      {value?.fit && value.fit !== "ok" ? (
        <div className="flex items-center gap-2">
          <Label htmlFor={amountId} className="text-[12px] font-normal text-muted">
            {t("coupon.how")}
          </Label>
          <Select
            id={amountId}
            className="h-7 text-[12px]"
            value={value.amount ?? ""}
            onChange={(e) => onChange({ ...value, amount: (e.target.value || null) as CouponAmount | null })}
          >
            <option value="barely">{t("coupon.barely")}</option>
            <option value="">{t("coupon.normal")}</option>
            <option value="very">{t("coupon.very")}</option>
          </Select>
        </div>
      ) : null}
    </fieldset>
  );
}

/**
 * The feedback control. `features` are the coupon's mating features (lib/coupon-fit `couponFeatures`). Link the report
 * to the job or part it came from with `jobId` / `slug`.
 */
export function CouponFit({ features, jobId, slug, className }: { features: CouponFeature[]; jobId?: string; slug?: string; className?: string }) {
  const { t } = useT();
  const caps = useCapabilities();
  const downloaded = useCouponDownloaded();
  const [open, setOpen] = React.useState(false);
  const learned = useLearnedClearances();
  const [presetId, setPresetId] = useRememberedPreset();
  const [answers, setAnswers] = React.useState<Answers>({});
  const [hint, setHint] = React.useState("");
  const qc = useQueryClient();
  const baseId = React.useId();
  const headingRef = React.useRef<HTMLHeadingElement>(null);
  React.useEffect(() => {
    if (open) headingRef.current?.focus(); // the reveal button is gone: keep keyboard focus in the new form
  }, [open]);
  const report = useMutation({
    mutationFn: (body: Parameters<typeof api.couponReport>[0]) => api.couponReport(body),
    onSuccess: () => {
      setAnswers({});
      void qc.invalidateQueries({ queryKey: ["coupon-learned"] });
    },
  });

  if (!caps.has("post", "/fit-reports/coupon")) return null;
  const list = [...learned.byId.values()];
  const preset = learned.byId.get(presetId) ?? null;
  const shown = downloaded || open;

  if (!shown)
    return (
      <div className={className}>
        <Button variant="link" size="sm" onClick={() => setOpen(true)}>
          <Ruler aria-hidden /> {t("coupon.reveal")}
        </Button>
      </div>
    );

  const result = report.data?.learned ?? preset;
  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!learned.session || !presetId) return;
    const body = reportBody(presetId, learned.session, answers, { jobId, slug });
    if (!body.features.length) {
      setHint(t("coupon.pickOne"));
      return;
    }
    setHint("");
    report.mutate(body);
  };

  return (
    <form onSubmit={submit} className={cn("space-y-3", className)} aria-labelledby={`${baseId}-title`}>
      <div className="space-y-0.5">
        <h3 id={`${baseId}-title`} ref={headingRef} tabIndex={-1} className="text-[13px] font-medium text-fg outline-none">
          {t("coupon.title")}
        </h3>
        <p className="text-[12px] leading-5 text-muted">{t("coupon.intro")}</p>
      </div>
      {!learned.session ? (
        <p className="text-[12px] text-muted">{t("coupon.noDevice")}</p>
      ) : (
        <>
          <div className="space-y-1.5">
            <Label htmlFor={`${baseId}-preset`}>{t("coupon.printer")}</Label>
            <Select id={`${baseId}-preset`} className="w-full" value={presetId} onChange={(e) => setPresetId(e.target.value)} required>
              <option value="">{t("presets.pick")}</option>
              {list.map((l) => (
                <option key={l.preset} value={l.preset}>
                  {l.title}
                </option>
              ))}
            </Select>
          </div>
          {presetId ? (
            <div className="space-y-3">
              {features.map((f, i) => (
                <FeatureRow key={f.id} f={f} name={`${baseId}-f${i}`} value={answers[f.id]} onChange={(v) => setAnswers((cur) => ({ ...cur, [f.id]: v }))} />
              ))}
              <div className="flex flex-wrap items-center gap-3">
                <Button type="submit" size="sm" variant="outline" disabled={report.isPending}>
                  {t("coupon.send")}
                </Button>
                {hint ? <span className="text-[12px] text-warn">{hint}</span> : null}
              </div>
            </div>
          ) : null}
          {report.isError ? <ErrorState error={report.error} compact what="your coupon report" /> : null}
          <div role="status" aria-live="polite" className="text-[12px] leading-5">
            {result && result.preset === presetId ? (
              <div className="space-y-0.5 rounded-md bg-surface-2 p-2.5">
                {report.isSuccess ? <p className="text-good">{t("coupon.sent")}</p> : null}
                <p>
                  {t("coupon.clearance", { preset: result.title, mm: `+${fmtMm(result.clearance_mm, 3)}` })}{" "}
                  <span className="text-muted">· {learnedLabel(result, t)}</span>
                </p>
                <p className="text-muted">{t("coupon.onlyClearance", { lo: fmtMm(result.range_mm[0], 2), hi: fmtMm(result.range_mm[1], 2) })}</p>
              </div>
            ) : null}
          </div>
        </>
      )}
    </form>
  );
}
