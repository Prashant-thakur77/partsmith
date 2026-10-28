"use client";

/**
 * Fit presets: pick the material and the printer, and the server's clearance for that pair (`GET /presets`, delta_mm)
 * is added to the internal-fit knobs (holes, bores, pins, cable channels, gaps, slots). On a part page the list of fit
 * knobs comes from `GET /parts/{slug}/presets`; in the workspace (no published part yet) the same rule picks them from
 * the knob specs. Values are snapped to each knob's range; the bake clamps again server-side.
 * When this device has reported how a printed fit-test coupon fit (`GET /fit-reports/coupon`), the learned clearance
 * for that printer + material replaces the preset's and is labelled with how many reports it came from.
 * Shown only when the API offers `/presets`.
 */
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { z } from "zod/mini";
import { API_PREFIX } from "@/lib/api";
import type { ParamSpec } from "@/lib/api-types";
import { useCapabilities } from "@/lib/capabilities";
import { fmtMm } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { Button } from "../ui/button";
import { Label, Select } from "../ui/input";
import { useLearnedClearances, useRememberedPreset } from "./coupon-fit";

const PresetSchema = z.object({
  id: z.string(),
  title: z.string(),
  material: z.string(),
  process: z.string(),
  nozzle_mm: z.nullish(z.number()),
  delta_mm: z.number(),
  note: z._default(z.string(), ""),
});
export type FitPreset = z.output<typeof PresetSchema>;
export const PresetListSchema = z.array(PresetSchema);
const PartPresetsSchema = z.object({ slug: z.string(), fit_knobs: z.array(z.string()), note: z._default(z.string(), "") });

const FIT_KEYS = ["hole", "bore", "pivot", "pin", "cable", "gap", "clearance", "slot"];

async function getJson<T>(path: string, schema: z.ZodMiniType<T>): Promise<T> {
  const res = await fetch(`${API_PREFIX}${path}`);
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  const parsed = schema.safeParse(await res.json());
  if (!parsed.success) {
    console.error(`[contract] ${path}`, parsed.error.issues);
    throw new Error(`${path}: unexpected shape (${parsed.error.issues[0]?.message ?? "?"})`);
  }
  return parsed.data;
}

export function usePresets() {
  const caps = useCapabilities();
  return useQuery({
    queryKey: ["presets"],
    enabled: caps.has("get", "/presets"),
    staleTime: Infinity,
    queryFn: () => getJson("/presets", PresetListSchema),
  });
}

function usePartFitKnobs(slug: string | undefined) {
  const caps = useCapabilities();
  return useQuery({
    queryKey: ["part-presets", slug],
    enabled: !!slug && caps.has("get", "/parts/{slug}/presets"),
    staleTime: 60_000,
    queryFn: () => getJson(`/parts/${encodeURIComponent(slug ?? "")}/presets`, PartPresetsSchema),
  });
}

function printerLabel(p: FitPreset): string {
  return p.nozzle_mm != null ? `${p.process} · ${fmtMm(p.nozzle_mm, 1)} nozzle` : p.process;
}

function snap(v: number, p: ParamSpec): number {
  const clamped = Math.min(p.max, Math.max(p.min, v));
  if (!(p.step > 0)) return clamped;
  const n = Math.round((clamped - p.min) / p.step);
  return Math.min(p.max, Number((p.min + n * p.step).toFixed(6)));
}

export type PresetChange = { param: string; from: number; to: number };

/** The changes a preset makes to `values` (fit knobs only). Exported for tests. */
export function presetChanges(preset: FitPreset, params: ParamSpec[], values: Record<string, number>, fitKnobs?: string[]): PresetChange[] {
  const fit = params.filter((p) =>
    fitKnobs ? fitKnobs.includes(p.name) : p.affects_fit && p.unit === "mm" && !p.topology && FIT_KEYS.some((k) => p.name.toLowerCase().includes(k)),
  );
  const out: PresetChange[] = [];
  for (const p of fit) {
    const from = values[p.name] ?? p.default;
    const to = snap(from + preset.delta_mm, p);
    if (Math.abs(to - from) > 1e-9) out.push({ param: p.name, from, to });
  }
  return out;
}

export function FitPresets({
  params,
  values,
  onApply,
  slug,
}: {
  params: ParamSpec[];
  values: Record<string, number>;
  onApply: (p: Record<string, number>) => void;
  slug?: string;
}) {
  const { t } = useT();
  const q = usePresets();
  const part = usePartFitKnobs(slug);
  const [material, setMaterial] = React.useState("");
  const [printer, setPrinter] = React.useState("");
  const [applied, setApplied] = React.useState<string | null>(null);
  const id = React.useId();
  const learned = useLearnedClearances();
  const [remembered, remember] = useRememberedPreset();
  // Start from the printer + material this device used last (also the coupon control's choice).
  const restored = React.useRef(false);
  React.useEffect(() => {
    const p = q.data?.find((x) => x.id === remembered);
    if (p && !restored.current) {
      restored.current = true;
      setMaterial(p.material);
      setPrinter(p.id);
    }
  }, [q.data, remembered]);

  if (q.isError) return <p className="mt-3 text-[12px] text-bad">{q.error instanceof Error ? q.error.message : "presets failed"}</p>;
  if (!q.data?.length) return null;
  const list = q.data;
  const materials = [...new Set(list.map((p) => p.material))];
  const printers = list.filter((p) => p.material === material);
  const base = printers.find((p) => p.id === printer) ?? (printers.length === 1 ? printers[0] : undefined);
  const learnedRow = base ? learned.byId.get(base.id) : undefined;
  const fromCoupon = learnedRow?.source === "learned" ? learnedRow : null;
  // The learned clearance only replaces the preset's delta; it never touches a measured knob.
  const preset = base && fromCoupon ? { ...base, delta_mm: fromCoupon.clearance_mm } : base;
  const changes = preset ? presetChanges(preset, params, values, part.data?.fit_knobs) : [];
  const label = (n: string) => params.find((p) => p.name === n)?.label || n;

  return (
    <div className="mt-4 space-y-3 border-t border-border pt-4">
      <p className="text-[13px] font-medium">{t("presets.title")}</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-m`}>{t("presets.material")}</Label>
          <Select
            id={`${id}-m`}
            className="w-full"
            value={material}
            onChange={(e) => {
              setMaterial(e.target.value);
              setPrinter("");
              setApplied(null);
            }}
          >
            <option value="">{t("presets.pick")}</option>
            {materials.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor={`${id}-p`}>{t("presets.printer")}</Label>
          <Select
            id={`${id}-p`}
            className="w-full"
            value={preset?.id ?? printer}
            disabled={!material}
            onChange={(e) => {
              setPrinter(e.target.value);
              setApplied(null);
              if (e.target.value) remember(e.target.value);
            }}
          >
            <option value="">{t("presets.pick")}</option>
            {printers.map((p) => (
              <option key={p.id} value={p.id}>
                {printerLabel(p)}
              </option>
            ))}
          </Select>
        </div>
      </div>
      {preset ? (
        <div className="space-y-2 rounded-md bg-surface-2 p-3 text-[12px] leading-5">
          <p>
            <span className="font-medium">{preset.title}</span>: +{fmtMm(preset.delta_mm, fromCoupon ? 3 : 2)} {t("presets.clearance")}
            {fromCoupon ? (
              <span className="text-muted">
                {" "}
                · {fromCoupon.reports === 1 ? t("presets.learnedOne") : t("presets.learned", { n: fromCoupon.reports })} (preset +{fmtMm(fromCoupon.preset_clearance_mm, 2)})
              </span>
            ) : null}
          </p>
          {changes.length ? (
            <ul className="space-y-0.5 font-mono tabular-nums">
              {changes.map((c) => (
                <li key={c.param}>
                  {label(c.param)} {fmtMm(c.from, 2)} → {fmtMm(c.to, 2)}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-muted">{t("presets.none")}</p>
          )}
          {preset.note ? <p className="text-muted">{preset.note}</p> : null}
          {fromCoupon ? null : <p className="text-muted">{t("presets.honest")}</p>}
          <div className="flex items-center gap-3">
            <Button
              size="sm"
              variant="outline"
              disabled={!changes.length}
              onClick={() => {
                onApply(Object.fromEntries(changes.map((c) => [c.param, c.to])));
                setApplied(preset.id);
              }}
            >
              {t("presets.apply")}
            </Button>
            {applied === preset.id ? (
              <span role="status" className="text-good">
                {t("presets.applied")}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
