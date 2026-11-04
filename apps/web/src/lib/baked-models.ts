/**
 * Real CadQuery output baked ahead of time (tools/deck_data.py): `/deck/models/index.json` lists each knob's steps and each
 * step's mesh file. A slider moves between those real meshes; the browser never runs CAD and never scales a mesh to fake one.
 */
import { z } from "zod";

const StepSchema = z.object({
  value: z.number(),
  file: z.string(),
  size_mm: z.tuple([z.number(), z.number(), z.number()]),
  triangles: z.number(),
});

const KnobSchema = z.object({
  label: z.string(),
  unit: z.string(),
  default: z.number(),
  topology: z.boolean().optional(),
  steps: z.array(StepSchema).min(1),
});

const PartSchema = z.object({
  title: z.string(),
  status: z.string(),
  max_error_mm: z.number().nullable().optional(),
  knobs: z.record(z.string(), KnobSchema),
});

export const BakedIndexSchema = z.object({ parts: z.record(z.string(), PartSchema) });

export type BakedStep = z.infer<typeof StepSchema>;
export type BakedKnob = z.infer<typeof KnobSchema>;
export type BakedPart = z.infer<typeof PartSchema>;
export type BakedIndex = z.infer<typeof BakedIndexSchema>;

export const BAKED_INDEX_URL = "/deck/models/index.json";

export async function fetchBakedIndex(signal?: AbortSignal): Promise<BakedIndex> {
  const r = await fetch(BAKED_INDEX_URL, { signal });
  if (!r.ok) throw new Error(`baked models: ${r.status}`);
  return BakedIndexSchema.parse(await r.json());
}

/** Where a step's mesh is served from: the index stores paths relative to the deck. */
export function meshUrl(file: string): string {
  return file.startsWith("/") ? file : `/deck/${file}`;
}

/** The index of the step nearest the knob's default: where a slider starts. */
export function defaultStepIndex(knob: BakedKnob): number {
  let best = 0;
  knob.steps.forEach((s, i) => {
    if (Math.abs(s.value - knob.default) < Math.abs(knob.steps[best]!.value - knob.default)) best = i;
  });
  return best;
}

/** The largest size any step reaches, so a fixed camera shows the part growing rather than refitting to hide it. */
export function largestSizeMm(knob: BakedKnob): number {
  return Math.max(...knob.steps.flatMap((s) => s.size_mm));
}

/** A mesh file: little-endian u32 vertex count and face count, then float32 xyz positions and u32 triangle indices. */
export function decodeMesh(buf: ArrayBuffer): { positions: Float32Array; indices: Uint32Array } {
  if (buf.byteLength < 8) throw new Error("mesh file too short");
  const [nv, nf] = new Uint32Array(buf, 0, 2) as unknown as [number, number];
  const need = 8 + nv * 12 + nf * 12;
  if (buf.byteLength < need) throw new Error(`mesh file truncated: ${buf.byteLength} of ${need} bytes`);
  return { positions: new Float32Array(buf, 8, nv * 3), indices: new Uint32Array(buf, 8 + nv * 12, nf * 3) };
}
