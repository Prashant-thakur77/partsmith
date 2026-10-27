/** Parsing for the geom worker's `view.json`: triangles + B-rep edge polylines, millimetres, CAD frame (Z up). */
import { z } from "zod/mini";

const nums = z.array(z.number());

export const ViewJsonSchema = z.object({
  units: z._default(z.literal("mm"), "mm"),
  bbox: z.optional(z.union([nums, z.array(nums), z.object({ min: nums, max: nums }), z.record(z.string(), z.number())])),
  mesh: z.object({ positions: nums, normals: z.optional(nums), indices: z.optional(nums) }),
  edges: z._default(z.array(nums), []),
});

export type ViewData = {
  positions: Float32Array;
  normals: Float32Array | null;
  indices: Uint32Array | null;
  /** Edge segments as pairs of points (x0,y0,z0,x1,y1,z1, ...). */
  segments: Float32Array;
  min: [number, number, number];
  max: [number, number, number];
};

function bboxFrom(raw: z.output<typeof ViewJsonSchema>["bbox"], positions: Float32Array): Pick<ViewData, "min" | "max"> {
  const fromPositions = () => {
    const min: [number, number, number] = [Infinity, Infinity, Infinity];
    const max: [number, number, number] = [-Infinity, -Infinity, -Infinity];
    for (let i = 0; i < positions.length; i += 3) {
      for (let k = 0; k < 3; k++) {
        const v = positions[i + k] ?? 0;
        if (v < min[k]!) min[k] = v;
        if (v > max[k]!) max[k] = v;
      }
    }
    return { min, max };
  };
  if (!raw) return fromPositions();
  if (Array.isArray(raw) && raw.length === 6 && typeof raw[0] === "number") {
    const b = raw as number[];
    return { min: [b[0]!, b[1]!, b[2]!], max: [b[3]!, b[4]!, b[5]!] };
  }
  if (Array.isArray(raw) && raw.length === 2 && Array.isArray(raw[0])) {
    const [a, b] = raw as number[][];
    return { min: [a![0]!, a![1]!, a![2]!], max: [b![0]!, b![1]!, b![2]!] };
  }
  if (!Array.isArray(raw) && "min" in raw && Array.isArray(raw.min)) {
    const r = raw as { min: number[]; max: number[] };
    return { min: [r.min[0]!, r.min[1]!, r.min[2]!], max: [r.max[0]!, r.max[1]!, r.max[2]!] };
  }
  if (!Array.isArray(raw) && "xmin" in raw) {
    const r = raw as Record<string, number>;
    return { min: [r.xmin!, r.ymin!, r.zmin!], max: [r.xmax!, r.ymax!, r.zmax!] };
  }
  return fromPositions();
}

export function parseViewJson(input: unknown): ViewData {
  const v = ViewJsonSchema.parse(input);
  const positions = new Float32Array(v.mesh.positions);
  const normals = v.mesh.normals && v.mesh.normals.length === v.mesh.positions.length ? new Float32Array(v.mesh.normals) : null;
  const indices = v.mesh.indices && v.mesh.indices.length ? new Uint32Array(v.mesh.indices) : null;
  let count = 0;
  for (const pl of v.edges) count += Math.max(0, pl.length / 3 - 1);
  const segments = new Float32Array(count * 6);
  let o = 0;
  for (const pl of v.edges) {
    for (let i = 0; i + 5 < pl.length; i += 3) {
      segments.set(pl.slice(i, i + 6), o);
      o += 6;
    }
  }
  return { positions, normals, indices, segments, ...bboxFrom(v.bbox, positions) };
}

export async function fetchViewData(url: string, signal?: AbortSignal): Promise<ViewData> {
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`view.json ${res.status}`);
  return parseViewJson(await res.json());
}
