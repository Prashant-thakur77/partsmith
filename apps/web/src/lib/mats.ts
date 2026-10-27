/** Screen-mat helpers: load layouts (API first, static copy in /public/mats as fallback) and pick the largest that fits. */
import { api, isOffline } from "./api";
import { MatLayoutSchema, type MatLayout } from "./api-types";

export async function loadScreenMats(): Promise<{ mats: MatLayout[]; source: "api" | "static" }> {
  try {
    const mats = await api.mats();
    return { mats: mats.filter((m) => m.kind === "screen"), source: "api" };
  } catch (err) {
    // Only an unreachable API falls back to the static copies; contract errors must surface.
    if (!isOffline(err)) throw err;
    // index.json (written by `tools/mat/make_mat.py --web`): [{mat_id, kind, url, ...}]
    const index = await fetch("/mats/index.json").then((r) => (r.ok ? (r.json() as Promise<{ mat_id: string; kind: string; url?: string }[]>) : []));
    const mats: MatLayout[] = [];
    for (const entry of index.filter((e) => e.kind === "screen")) {
      const res = await fetch(entry.url ?? `/mats/${entry.mat_id}.json`);
      if (!res.ok) continue;
      const parsed = MatLayoutSchema.safeParse(await res.json());
      if (parsed.success && parsed.data.kind === "screen") mats.push(parsed.data);
    }
    return { mats, source: "static" };
  }
}

/** Largest screen mat whose full layout fits in the viewport (CSS px) at the calibrated scale. */
export function pickMat(mats: MatLayout[], viewportW: number, viewportH: number, pxPerMm: number, marginPx = 0): MatLayout | null {
  const fits = mats
    .filter((m) => m.width_mm * pxPerMm <= viewportW - marginPx && m.height_mm * pxPerMm <= viewportH - marginPx)
    .sort((a, b) => b.width_mm * b.height_mm - a.width_mm * a.height_mm);
  return fits[0] ?? null;
}
