/**
 * Geometry for the drawings on the landing page and /how: fit a measured outline (mm, y up) into an SVG box (y down),
 * marker bit patterns, and path strings. Pure, so `node --test` can load it. Values in mm stay in mm; only the mapping
 * to screen units happens here.
 */

export type Pt = readonly [number, number];
export type Box = { x: number; y: number; w: number; h: number };

export type Fitted = {
  /** mm → svg */
  map: (p: Pt) => [number, number];
  /** svg units per mm */
  scale: number;
  /** outline bounding box in svg units */
  bbox: Box;
  /** outline bounding box in mm (min x, min y, max x, max y) */
  mm: { x0: number; y0: number; x1: number; y1: number };
};

/** Scale and centre points (mm, y up) into `box` (svg, y down), keeping aspect. Empty input maps to the box centre. */
export function fitPoints(points: readonly Pt[], box: Box, pad = 0): Fitted {
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const x0 = xs.length ? Math.min(...xs) : 0;
  const x1 = xs.length ? Math.max(...xs) : 0;
  const y0 = ys.length ? Math.min(...ys) : 0;
  const y1 = ys.length ? Math.max(...ys) : 0;
  const w = Math.max(1e-6, x1 - x0);
  const h = Math.max(1e-6, y1 - y0);
  const scale = Math.min((box.w - 2 * pad) / w, (box.h - 2 * pad) / h);
  const cx = box.x + box.w / 2;
  const cy = box.y + box.h / 2;
  const mx = (x0 + x1) / 2;
  const my = (y0 + y1) / 2;
  const map = (p: Pt): [number, number] => [cx + (p[0] - mx) * scale, cy - (p[1] - my) * scale];
  return { map, scale, bbox: { x: cx - (w * scale) / 2, y: cy - (h * scale) / 2, w: w * scale, h: h * scale }, mm: { x0, y0, x1, y1 } };
}

/** Closed SVG path through mapped points ("M x y L … Z"), rounded to 0.1 units. */
export function pathOf(points: readonly Pt[], map: (p: Pt) => [number, number]): string {
  if (!points.length) return "";
  const r = (v: number) => Math.round(v * 10) / 10;
  return points.map((p, i) => {
    const [x, y] = map(p);
    return `${i ? "L" : "M"}${r(x)} ${r(y)}`;
  }).join(" ") + " Z";
}

/** Signed area (shoelace); positive when counter-clockwise in a y-up frame. */
export function signedArea(points: readonly Pt[]): number {
  let a = 0;
  for (let i = 0; i < points.length; i++) {
    const p = points[i]!;
    const q = points[(i + 1) % points.length]!;
    a += p[0] * q[1] - q[0] * p[1];
  }
  return a / 2;
}

/** The outline grown outwards by `d` (mm) along each vertex's averaged normal: a "model" drawn a hair off the photo. */
export function offsetOutline(points: readonly Pt[], d: number): Pt[] {
  const n = points.length;
  if (n < 3) return [...points];
  const s = signedArea(points) >= 0 ? 1 : -1;
  return points.map((p, i) => {
    const a = points[(i - 1 + n) % n]!;
    const b = points[(i + 1) % n]!;
    const tx = b[0] - a[0];
    const ty = b[1] - a[1];
    const len = Math.hypot(tx, ty) || 1;
    // outward normal of a CCW polygon is (ty, -tx)
    return [p[0] + (s * ty * d) / len, p[1] - (s * tx * d) / len] as Pt;
  });
}

/** Index of the outline point nearest to `q` (mm). */
export function nearestIndex(points: readonly Pt[], q: Pt): number {
  let best = -1;
  let bd = Infinity;
  points.forEach((p, i) => {
    const d = Math.hypot(p[0] - q[0], p[1] - q[1]);
    if (d < bd) {
      bd = d;
      best = i;
    }
  });
  return best;
}

/**
 * A 4×4 marker pattern (16 bits, row-major) for a marker id: deterministic, never all-black or all-white rows, so the
 * drawing reads as fiducial markers. Decorative only — the real mats come from the API.
 */
export function markerBits(id: number): boolean[] {
  let x = (id + 1) * 2654435761;
  const bits: boolean[] = [];
  for (let i = 0; i < 16; i++) {
    x = (x ^ (x << 13)) >>> 0;
    x = (x ^ (x >>> 17)) >>> 0;
    x = (x ^ (x << 5)) >>> 0;
    bits.push((x & 8) !== 0);
  }
  for (let r = 0; r < 4; r++) {
    const row = bits.slice(r * 4, r * 4 + 4);
    if (row.every(Boolean)) bits[r * 4 + ((id + r) % 4)] = false;
    if (row.every((b) => !b)) bits[r * 4 + ((id + r + 1) % 4)] = true;
  }
  return bits;
}

/** A point on a circle (degrees, 0 = up, clockwise) — used by the loop ring. */
export function onCircle(cx: number, cy: number, r: number, deg: number): [number, number] {
  const a = ((deg - 90) * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}

/** Arc path from `a0` to `a1` degrees (clockwise, 0 = up). */
export function arcPath(cx: number, cy: number, r: number, a0: number, a1: number): string {
  const [x0, y0] = onCircle(cx, cy, r, a0);
  const [x1, y1] = onCircle(cx, cy, r, a1);
  const large = (((a1 - a0) % 360) + 360) % 360 > 180 ? 1 : 0;
  const f = (v: number) => Math.round(v * 100) / 100;
  return `M${f(x0)} ${f(y0)} A${f(r)} ${f(r)} 0 ${large} 1 ${f(x1)} ${f(y1)}`;
}

/** Radius for an error value inside the loop ring's gauge: linear in mm between rMin (0 mm) and rMax (maxMm). */
export function gaugeRadius(mm: number, maxMm: number, rMin: number, rMax: number): number {
  if (!Number.isFinite(mm) || maxMm <= 0) return rMin;
  const k = Math.min(1, Math.max(0, mm / maxMm));
  return rMin + (rMax - rMin) * k;
}
