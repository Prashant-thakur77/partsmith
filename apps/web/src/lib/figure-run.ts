/**
 * Which stored run the landing drawings use, and the numbers they print — all read from `/replays` and the job detail
 * (no ids or values typed here). Free of runtime imports so `node --test` can load it directly.
 */
import type { JobDetail, Replay } from "./api-types";

/** "· review round 4" → 4 (same rule as replays.ts, repeated so this file has no runtime imports). */
function round(title: string): number | null {
  const m = /review round (\d+)/i.exec(title);
  return m ? Number(m[1]) : null;
}

/**
 * The run for Fig. 1: the verified last round of a human review chain (the most rounds), else the verified run that took
 * the most rounds to fix, else any verified run, else the first stored run. Null for an empty list.
 */
export function pickFigureRun(replays: readonly Replay[]): Replay | null {
  const err = (r: Replay) => r.max_error_mm ?? Number.POSITIVE_INFINITY;
  const reviewed = replays.filter((r) => r.verified && round(r.title) != null).sort((a, b) => round(b.title)! - round(a.title)!)[0];
  if (reviewed) return reviewed;
  const fixed = replays.filter((r) => r.verified).sort((a, b) => b.iterations - a.iterations || err(a) - err(b))[0];
  return fixed ?? replays[0] ?? null;
}

/** The run that shows the loop fixing itself: verified after the most rounds (no review chain), else the most rounds. */
export function pickLoopRun(replays: readonly Replay[]): Replay | null {
  const err = (r: Replay) => r.max_error_mm ?? Number.POSITIVE_INFINITY;
  const plain = replays.filter((r) => round(r.title) == null);
  return (
    plain.filter((r) => r.verified && r.iterations > 1).sort((a, b) => b.iterations - a.iterations || err(a) - err(b))[0] ??
    plain.filter((r) => r.verified).sort((a, b) => err(a) - err(b))[0] ??
    replays[0] ??
    null
  );
}

/** The latest round of a review chain (its review record holds every round), verified first. */
export function pickReviewRun(replays: readonly Replay[]): Replay | null {
  return (
    replays
      .filter((r) => round(r.title) != null)
      .sort((a, b) => Number(b.verified) - Number(a.verified) || round(b.title)! - round(a.title)!)[0] ?? null
  );
}

export type FigureHole = { id: string; center: [number, number]; diameterMm: number };

export type FigureData = {
  id: string;
  title: string;
  origin: JobDetail["summary"]["origin"];
  providerMode: string;
  outline: [number, number][];
  holes: FigureHole[];
  lengthMm: number | null;
  widthMm: number | null;
  maxErrorMm: number | null;
  limitMm: number | null;
  verified: boolean;
  status: string | null;
  viewUrl: string | null;
  /** worst point of the top view (mm, part frame) and its gap, when the verifier recorded one */
  worst: { at: [number, number]; gapMm: number } | null;
  /** max error after each iteration, in order (from the run's iteration events) */
  rounds: { iter: number; mm: number }[];
  /** knob name → value of the final program */
  values: Record<string, number>;
  params: JobDetail["params"];
  code: string | null;
  photo: string | null;
  rectified: string | null;
  mask: string | null;
};

/** Pull the drawing's numbers out of a job detail. Lengths stay in millimetres; nothing is rounded here. */
export function figureFromJob(d: JobDetail): FigureData {
  const top = d.measurements.top ?? Object.values(d.measurements)[0];
  const v = d.verification;
  const topView = v?.views.find((x) => x.view === "top") ?? v?.views[0];
  const rounds = d.events
    .filter((e): e is Extract<JobDetail["events"][number], { t: "iteration" }> => e.t === "iteration")
    .filter((e) => typeof e.hausdorff_mm === "number")
    .map((e) => ({ iter: e.iter, mm: e.hausdorff_mm as number }));
  // the top view's artifact when the run has several views ("top: rectified to the mat plane"), else the first one
  const art = (kind: string) => {
    const all = d.events.filter((e): e is Extract<JobDetail["events"][number], { t: "artifact" }> => e.t === "artifact" && e.kind === kind);
    const ev = all.find((e) => /^top\b/i.test(e.label)) ?? all[0];
    return ev ? ev.url : (d.artifacts[kind] ?? null);
  };
  return {
    id: d.summary.id,
    title: d.summary.title,
    origin: d.summary.origin,
    providerMode: d.summary.provider_mode,
    outline: (top?.outline_mm ?? []).map((p) => [p[0], p[1]] as [number, number]),
    holes: (top?.holes ?? []).map((h) => ({ id: h.id, center: [h.center_mm[0], h.center_mm[1]] as [number, number], diameterMm: h.diameter.value })),
    lengthMm: top?.length.value ?? null,
    widthMm: top?.width.value ?? null,
    maxErrorMm: v?.max_error_mm ?? d.summary.max_error_mm ?? null,
    limitMm: v?.thresholds.hausdorff_mm ?? null,
    verified: v?.verified ?? d.summary.verified,
    status: v?.status ?? null,
    viewUrl: d.artifacts.view ?? null,
    worst: topView?.worst_point_mm ? { at: [topView.worst_point_mm[0], topView.worst_point_mm[1]], gapMm: topView.hausdorff_mm } : null,
    rounds,
    values: d.values,
    params: d.params,
    code: d.code ?? null,
    photo: art("photo"),
    rectified: art("rectified"),
    mask: art("mask_overlay"),
  };
}

/**
 * Lines of the part program that define the knobs (the `PARAMS = {…}` block), up to `max` lines, each with the knob it
 * names. Falls back to the first lines that mention a knob name.
 */
export function knobLines(code: string | null, names: readonly string[], max = 8): { text: string; knob: string | null }[] {
  if (!code) return [];
  const lines = code.split("\n");
  const start = lines.findIndex((l) => /^\s*PARAMS\s*=/.test(l));
  const pick = (l: string) => names.find((n) => new RegExp(`["']${n}["']`).test(l)) ?? null;
  if (start >= 0) {
    const out: { text: string; knob: string | null }[] = [{ text: lines[start]!, knob: null }];
    for (let i = start + 1; i < lines.length && out.length < max; i++) {
      const l = lines[i]!;
      out.push({ text: l, knob: pick(l) });
      if (/^\s*}\s*$/.test(l)) break;
    }
    return out;
  }
  return lines.filter((l) => pick(l)).slice(0, max).map((l) => ({ text: l, knob: pick(l) }));
}

/**
 * The program's own map from measured quantities to knobs (`MEASURE_MAP = {"length": "length", "hole_1.diameter":
 * "hole_d", …}`), so a drawing can link a dimension to the knob it sets. Empty when the program has none.
 */
export function measureLinks(code: string | null): { measure: string; knob: string }[] {
  if (!code) return [];
  const m = /MEASURE_MAP\s*=\s*\{([\s\S]*?)\n\}/.exec(code);
  if (!m) return [];
  const out: { measure: string; knob: string }[] = [];
  for (const line of m[1]!.split("\n")) {
    const kv = /^\s*["']([\w.]+)["']\s*:\s*["'](\w+)["']/.exec(line);
    if (kv && !out.some((o) => o.measure === kv[1])) out.push({ measure: kv[1]!, knob: kv[2]! });
  }
  return out;
}

/** The measured value (mm) a MEASURE_MAP key refers to, from the run's own measurements; null when not measured. */
export function measuredValue(f: Pick<FigureData, "lengthMm" | "widthMm" | "holes">, measure: string): number | null {
  if (measure === "length") return f.lengthMm;
  if (measure === "width") return f.widthMm;
  const h = /^(hole_\d+)\.diameter$/.exec(measure);
  if (h) return f.holes.find((x) => x.id === h[1])?.diameterMm ?? null;
  return null;
}
