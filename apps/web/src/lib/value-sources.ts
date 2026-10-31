/**
 * "Where each value came from": one entry per value the job measured or used (overall sizes, feature sizes, the
 * rebuilt broken region, program knobs no test checked), each with its source kind, ± sigma, evidence note, the
 * artifacts it can be traced to and the verifier residuals that compared the model with it. The viewer and the
 * measurement panel colour by `SOURCE_STYLES`; the colour is never the only cue (each kind also has a text label,
 * an icon and a swatch pattern).
 *
 * Pure and free of runtime imports so `node --test` can load it directly. Nothing here makes or changes a number:
 * every value, sigma and residual is copied from the job detail the API returned.
 */
import type { ArtifactEvent, FeatureResidual, JobDetail, Measurements, Source, Verification } from "./api-types";

/** Display kinds. `pointed` and `completed` refine the schema's `Source` using the evidence the server recorded. */
export type SourceKind = "measured" | "pointed" | "user_stated" | "cited" | "inferred" | "completed";

export type SwatchPattern = "solid" | "dots" | "stripes" | "diagonal" | "hollow" | "crosshatch";
export type LineDash = "solid" | "dashed" | "dotted";
export type IconName = "ruler" | "mic" | "user" | "book" | "wand" | "puzzle";

export type SourceStyle = {
  label: string;
  /** One sentence for the legend and the detail panel. */
  description: string;
  icon: IconName;
  pattern: SwatchPattern;
  dash: LineDash;
  /** Text-safe on light surfaces (≥ 4.5:1 on white and on the light viewer background). */
  light: string;
  /** Text-safe on dark surfaces (≥ 4.5:1 on the dark surface and viewer background). */
  dark: string;
};

export const SOURCE_KINDS: readonly SourceKind[] = ["measured", "pointed", "user_stated", "cited", "inferred", "completed"];

export const SOURCE_STYLES: Record<SourceKind, SourceStyle> = {
  measured: {
    label: "Measured",
    description: "Measured by code from the photo on the calibrated mat.",
    icon: "ruler",
    pattern: "solid",
    dash: "solid",
    light: "#1f5fbf",
    dark: "#86b4ff",
  },
  pointed: {
    label: "Pointed in narration",
    description: "Muse Spark pointed at it in the walk-around clip; code checked the point and measured it.",
    icon: "mic",
    pattern: "dots",
    dash: "solid",
    light: "#00727f",
    dark: "#4dd2dc",
  },
  user_stated: {
    label: "You stated",
    description: "A value you typed or said, used as given; the photo did not measure it.",
    icon: "user",
    pattern: "stripes",
    dash: "dashed",
    light: "#7b3fb5",
    dark: "#cfa8ff",
  },
  cited: {
    label: "Cited",
    description: "Found by a web search with a citation; never overrides a measured value.",
    icon: "book",
    pattern: "diagonal",
    dash: "dashed",
    light: "#2e7531",
    dark: "#86d68a",
  },
  inferred: {
    label: "Inferred",
    description: "Not visible in the photo: a template default or a value inferred from the rest of the part.",
    icon: "wand",
    pattern: "hollow",
    dash: "dotted",
    light: "#9c4a00",
    dark: "#ffb469",
  },
  completed: {
    label: "Completed region",
    description: "A broken region rebuilt from evidence (mirror, template or a code-gated image completion); not measured.",
    icon: "puzzle",
    pattern: "crosshatch",
    dash: "dashed",
    light: "#ad1f6b",
    dark: "#ff94cc",
  },
};

/** Evidence note the server puts on every value measured from a narrated point (services/metrology/narration.py). */
const NARRATION_NOTE = "pointed by Spark (narration)";
const SOURCES: readonly Source[] = ["measured", "user_stated", "inferred", "cited"];

/** Display kind for a schema source plus its evidence note. */
export function sourceKind(source: string | null | undefined, note?: string | null): SourceKind {
  const s = (SOURCES as readonly string[]).includes(source ?? "") ? (source as Source) : "measured";
  if (s === "measured" && note && note.includes(NARRATION_NOTE)) return "pointed";
  return s;
}

// ── colour maths (WCAG 2.x relative luminance), exported for the contrast test ────────────────────────────────────────

export function relativeLuminance(hex: string): number {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) throw new Error(`not a #rrggbb colour: ${hex}`);
  const n = m[1]!;
  const ch = [0, 2, 4].map((i) => parseInt(n.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * ch[0]! + 0.7152 * ch[1]! + 0.0722 * ch[2]!;
}

/** WCAG contrast ratio between two colours given as #rrggbb or as relative luminance. */
export function contrastRatio(a: string | number, b: string | number): number {
  const x = typeof a === "number" ? a : relativeLuminance(a);
  const y = typeof b === "number" ? b : relativeLuminance(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

/** CSS background for a legend swatch: the pattern is drawn in the kind's colour (`currentColor`). */
export function swatchCss(pattern: SwatchPattern): { backgroundImage?: string; backgroundColor?: string; backgroundSize?: string; border: string } {
  switch (pattern) {
    case "solid":
      return { backgroundColor: "currentColor", border: "1.5px solid currentColor" };
    case "dots":
      return { backgroundImage: "radial-gradient(currentColor 1.2px, transparent 1.4px)", backgroundSize: "4px 4px", border: "1.5px solid currentColor" };
    case "stripes":
      return { backgroundImage: "repeating-linear-gradient(0deg, currentColor 0 1.5px, transparent 1.5px 4px)", border: "1.5px solid currentColor" };
    case "diagonal":
      return { backgroundImage: "repeating-linear-gradient(45deg, currentColor 0 1.5px, transparent 1.5px 4px)", border: "1.5px solid currentColor" };
    case "hollow":
      return { border: "1.5px dashed currentColor" };
    case "crosshatch":
      return {
        backgroundImage:
          "repeating-linear-gradient(45deg, currentColor 0 1px, transparent 1px 4px), repeating-linear-gradient(-45deg, currentColor 0 1px, transparent 1px 4px)",
        border: "1.5px solid currentColor",
      };
  }
}

// ── items ──────────────────────────────────────────────────────────────────────────────────────────────────────────

export type ValueAnchor =
  | { type: "dim"; axis: "x" | "y" | "z" }
  | { type: "point"; at: [number, number] }
  | { type: "polygon"; points: [number, number][] };

export type EvidenceLink = { label: string; url: string };

export type ValueItem = {
  /** Stable id: `dim.length`, `feature.hole_1.diameter`, `region.broken`, `knob.corner_radius`. */
  id: string;
  group: "dimension" | "feature" | "region" | "knob";
  label: string;
  /** Feature id for feature values (several values of one feature share its marker in the viewer). */
  featureId: string | null;
  kind: SourceKind;
  value: number | null;
  unit: "mm" | "deg" | "";
  sigmaMm: number | null;
  boundMm: [number, number] | null;
  note: string | null;
  view: string | null;
  citation: { url: string; title: string; quote: string } | null;
  /** Listed in `Verification.unchecked`: no test compared it with a photo. */
  unchecked: boolean;
  /** The verifier's residuals that compared the model with this value (empty when none did). */
  residuals: FeatureResidual[];
  evidence: EvidenceLink[];
  /** Where the viewer can draw it; null = side list only. */
  anchor: ValueAnchor | null;
};

type LooseMeasured = {
  value: number;
  source: string;
  sigma_mm: number;
  note: string | null;
  view: string | null;
  citation: ValueItem["citation"];
  bound_mm: [number, number] | null;
};

function asMeasured(x: unknown): LooseMeasured | null {
  if (!x || typeof x !== "object") return null;
  const o = x as Record<string, unknown>;
  if (typeof o.value !== "number" || !Number.isFinite(o.value)) return null;
  const ev = o.evidence && typeof o.evidence === "object" ? (o.evidence as Record<string, unknown>) : null;
  const c = ev?.citation && typeof ev.citation === "object" ? (ev.citation as Record<string, unknown>) : null;
  const b = Array.isArray(o.bound_mm) && o.bound_mm.length === 2 && o.bound_mm.every((v) => typeof v === "number" && Number.isFinite(v)) ? (o.bound_mm as [number, number]) : null;
  return {
    value: o.value,
    source: typeof o.source === "string" ? o.source : "measured",
    sigma_mm: typeof o.sigma_mm === "number" && Number.isFinite(o.sigma_mm) ? o.sigma_mm : 0,
    note: typeof ev?.note === "string" && ev.note ? ev.note : null,
    view: typeof ev?.view === "string" && ev.view ? ev.view : null,
    citation: c && typeof c.url === "string" ? { url: c.url, title: typeof c.title === "string" ? c.title : "", quote: typeof c.quote === "string" ? c.quote : "" } : null,
    bound_mm: b,
  };
}

function asPoint(x: unknown): [number, number] | null {
  return Array.isArray(x) && x.length >= 2 && typeof x[0] === "number" && typeof x[1] === "number" && Number.isFinite(x[0]) && Number.isFinite(x[1])
    ? [x[0], x[1]]
    : null;
}

const QUANTITY_LABEL: Record<string, string> = {
  diameter: "Ø",
  depth: "depth",
  length: "length",
  width: "width",
  outer_d: "outer Ø",
  inner_d: "inner Ø",
  height: "height",
  overhang: "overhang",
  thickness: "thickness",
  radius: "radius",
  flat_depth: "flat depth",
};

const humanId = (id: string) => id.replaceAll("_", " ");

/** Overlay or photo artifacts for a view, newest last, labelled as the server labelled them. */
function viewEvidence(artifacts: ArtifactEvent[], view: string | null, featureId: string | null): EvidenceLink[] {
  if (!view) return [];
  const out: EvidenceLink[] = [];
  const re = new RegExp(`^${view}\\b`, "i");
  const pick = (kind: string) => artifacts.filter((a) => a.kind === kind && a.iter == null && re.test(a.label)).at(-1);
  const overlay = pick("measure_overlay");
  if (overlay) out.push({ label: overlay.label || `${view} measurement overlay`, url: overlay.url });
  if (featureId) {
    const mask = artifacts.filter((a) => a.kind === "feature_mask" && a.label.includes(featureId)).at(-1);
    if (mask) out.push({ label: mask.label, url: mask.url });
  }
  if (!out.length) {
    const photo = pick("photo") ?? artifacts.find((a) => a.kind === "photo" && a.label.toLowerCase().startsWith(view));
    if (photo) out.push({ label: photo.label || `${view} photo`, url: photo.url });
  }
  return out;
}

export type ValueItemsInput = {
  partspec: JobDetail["partspec"];
  measurements: Record<string, Measurements>;
  verification: Verification | null | undefined;
  artifacts: ArtifactEvent[];
};

/**
 * Every value the job shows, in the order the side list reads: overall sizes, feature sizes, the rebuilt region, then
 * knobs no test checked.
 */
export function valueItems({ partspec, measurements, verification, artifacts }: ValueItemsInput): ValueItem[] {
  const residuals = verification?.residuals ?? [];
  const resFor = (feature: string, quantities: string[]) => residuals.filter((r) => r.feature_id === feature && quantities.includes(r.quantity));
  const narrationUrl = artifacts.filter((a) => a.kind === "narration").at(-1)?.url ?? null;
  const items: ValueItem[] = [];

  const fromMeasured = (
    m: LooseMeasured,
    base: Pick<ValueItem, "id" | "group" | "label" | "featureId" | "anchor">,
    res: FeatureResidual[],
    fallbackView: string | null,
  ): ValueItem => {
    const kind = sourceKind(m.source, m.note);
    const view = m.view ?? (kind === "measured" || kind === "pointed" ? fallbackView : null);
    const evidence = kind === "user_stated" || kind === "cited" ? [] : viewEvidence(artifacts, view, base.featureId);
    if (kind === "pointed" && narrationUrl) evidence.push({ label: "narration record (what was pointed at and kept)", url: narrationUrl });
    return {
      ...base,
      kind,
      value: m.value,
      unit: "mm",
      sigmaMm: m.sigma_mm > 0 ? m.sigma_mm : null,
      boundMm: m.bound_mm,
      note: m.note,
      view,
      citation: m.citation,
      unchecked: false,
      residuals: res,
      evidence,
    };
  };

  // overall sizes: the top view's footprint, the stated/measured thickness, the side view's height
  const top = measurements.top ?? Object.values(measurements)[0];
  if (top) {
    const len = asMeasured(top.length);
    const wid = asMeasured(top.width);
    if (len) items.push(fromMeasured(len, { id: "dim.length", group: "dimension", label: "Length", featureId: null, anchor: { type: "dim", axis: "x" } }, resFor("outline", ["length"]), top.view));
    if (wid) items.push(fromMeasured(wid, { id: "dim.width", group: "dimension", label: "Width", featureId: null, anchor: { type: "dim", axis: "y" } }, resFor("outline", ["width"]), top.view));
  }
  const thick = asMeasured(partspec?.thickness) ?? asMeasured(top?.thickness);
  if (thick) {
    // A plate's thickness is not the model's overall height (brackets, knobs): side list only.
    items.push(fromMeasured(thick, { id: "dim.thickness", group: "dimension", label: "Thickness", featureId: null, anchor: null }, resFor("plate", ["thickness"]), top?.view ?? null));
  }
  const side = measurements.side;
  const height = asMeasured(side?.thickness);
  if (side && height) {
    items.push(fromMeasured(height, { id: "dim.height", group: "dimension", label: "Side photo, short side", featureId: null, anchor: { type: "dim", axis: "z" } }, resFor("side", ["thickness"]), "side"));
  }

  // feature sizes: every Measured field of every PartSpec feature
  for (const f of partspec?.features ?? []) {
    const raw = f as Record<string, unknown>;
    const at = asPoint(raw.center_mm);
    let first = true;
    for (const [key, val] of Object.entries(raw)) {
      const m = asMeasured(val);
      if (!m) continue;
      const qs = first ? [key, "center_x", "center_y", "position"] : [key];
      first = false;
      items.push(
        fromMeasured(
          m,
          {
            id: `feature.${f.id}.${key}`,
            group: "feature",
            label: `${humanId(f.id)} ${QUANTITY_LABEL[key] ?? humanId(key)}`,
            featureId: f.id,
            anchor: at ? { type: "point", at } : null,
          },
          resFor(f.id, qs),
          "top",
        ),
      );
    }
  }

  // the rebuilt broken region
  const br = partspec?.broken_region;
  if (br) {
    const recon = artifacts.filter((a) => a.kind === "reconstruction");
    const aiAccepted = recon.some((a) => /accepted by code gate/i.test(a.label));
    const how =
      aiAccepted
        ? "Muse Image proposed the missing piece and the code gate accepted it; it enters the outline as inferred."
        : br.strategy === "mirror"
          ? "Rebuilt by code by mirroring the intact side."
          : br.strategy === "template"
            ? "Rebuilt from the part template's intact shape."
            : br.strategy === "mating_part"
              ? "Rebuilt to fit the mating part."
              : "Rebuilt from your description.";
    const poly = br.polygon_mm.filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));
    items.push({
      id: "region.broken",
      group: "region",
      label: br.kind === "height" ? "Broken top (above the break height)" : "Broken region",
      featureId: null,
      kind: "completed",
      value: null,
      unit: "mm",
      sigmaMm: null,
      boundMm: null,
      note: [how, br.note].filter(Boolean).join(" · "),
      view: "top",
      citation: null,
      unchecked: false,
      residuals: [],
      evidence: recon.map((a) => ({ label: a.label || "reconstruction", url: a.url })),
      anchor: br.kind !== "height" && poly.length >= 3 ? { type: "polygon", points: poly } : null,
    });
  }

  // program knobs no test compared with a photo
  for (const u of verification?.unchecked ?? []) {
    items.push({
      id: `knob.${u.param}`,
      group: "knob",
      label: u.label && u.label !== u.param ? `${u.label} (${u.param})` : humanId(u.param),
      featureId: null,
      kind: sourceKind(u.source, null),
      value: u.value,
      unit: u.unit,
      sigmaMm: null,
      boundMm: null,
      note: u.note || null,
      view: null,
      citation: null,
      unchecked: true,
      residuals: [],
      evidence: [],
      anchor: null,
    });
  }
  return items;
}

/** Counts per kind, in legend order, only for kinds present. */
export function kindCounts(items: ValueItem[]): { kind: SourceKind; count: number }[] {
  return SOURCE_KINDS.map((kind) => ({ kind, count: items.filter((i) => i.kind === kind).length })).filter((x) => x.count > 0);
}

/** "3.59 ± 0.05 mm" (or "—"), plain text for aria labels and the detail panel. */
export function valueText(item: Pick<ValueItem, "value" | "unit" | "sigmaMm">): string {
  if (item.value == null || !Number.isFinite(item.value)) return "—";
  const u = item.unit === "deg" ? "°" : item.unit ? ` ${item.unit}` : "";
  const s = item.sigmaMm ? ` ± ${item.sigmaMm.toFixed(2)}` : "";
  return `${item.value.toFixed(2)}${s}${u}`;
}

/** One line on whether a photo checked the value, from the verifier's own data. */
export function checkText(item: Pick<ValueItem, "unchecked" | "residuals" | "kind" | "group">): string {
  if (item.unchecked) return "Not checked against a photo.";
  if (item.group === "region") return "Left out of the comparison with the photo (the photo cannot show a missing piece).";
  if (!item.residuals.length) return "No feature test compared the model with this value.";
  const failed = item.residuals.filter((r) => !r.passed).length;
  return failed
    ? `The verifier compared the model with it: ${failed} of ${item.residuals.length} check(s) out of tolerance.`
    : `The verifier compared the model with it: ${item.residuals.length} check(s) within tolerance.`;
}
