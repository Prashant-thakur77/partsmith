/**
 * Download file names, the same rule the API uses for Content-Disposition (services/registry/filenames.py):
 * `partsmith-<slug>-<knobs that differ from the defaults>.<ext>`, e.g. `partsmith-cable-clip-hole3.4.stl`.
 * Safe ASCII only, at most 80 characters with the extension. Pure and free of runtime imports so `node --test` can load it.
 */

export const MAX_LEN = 80;

export function safe(text: string): string {
  return text
    .toLowerCase()
    .split(/[^a-z0-9.]+/)
    .map((w) => w.replace(/^\.+|\.+$/g, ""))
    .filter(Boolean)
    .join("-")
    .replace(/^[.-]+|[.-]+$/g, "");
}

export function knobShort(name: string): string {
  let parts = name.toLowerCase().split("_").filter(Boolean);
  if (parts.length > 1 && parts[parts.length - 1]!.length === 1) parts = parts.slice(0, -1);
  return parts.join("").replace(/[^a-z0-9]/g, "") || "k";
}

/** Up to two decimals, no trailing zeros (same as the API's `num_text`). */
export function numText(v: number): string {
  const s = (Math.round(v * 100) / 100).toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  return s === "-0" || s === "" ? "0" : s;
}

export function knobSummary(values: Record<string, number>, defaults: Record<string, number>, order: string[] = []): string[] {
  const names = [...new Set([...order, ...Object.keys(defaults), ...Object.keys(values)])];
  const out: string[] = [];
  for (const n of names) {
    const v = values[n];
    if (v === undefined) continue;
    const d = defaults[n];
    if (d !== undefined && Math.abs(v - d) < 1e-9) continue;
    out.push(`${knobShort(n)}${numText(v)}`);
  }
  return out;
}

export function downloadName(slug: string, ext: string, values: Record<string, number> = {}, defaults: Record<string, number> = {}, order: string[] = []): string {
  const bare = ext.replace(/^\.+|\.+$/g, "");
  const e = bare ? "." + safe(bare).replace(/-/g, ".") : "";
  const budget = MAX_LEN - e.length;
  const base = `partsmith-${safe(slug) || "part"}`.slice(0, budget).replace(/[-.]+$/, "");
  const tokens = knobSummary(values, defaults, order);
  const full = [base, ...tokens].join("-");
  if (full.length <= budget) return full + e;
  let name = base;
  for (let i = 0; i < tokens.length; i++) {
    const tok = tokens[i]!;
    const tail = `-plus${tokens.length - i - 1}`;
    if (name.length + 1 + tok.length + tail.length > budget) {
      return name.length + tail.length + 1 <= budget ? `${name}-plus${tokens.length - i}${e}` : name + e;
    }
    name = `${name}-${tok}`;
  }
  return name + e;
}

/** File extension per bake format (the API's EXTENSIONS). */
export const FORMAT_EXT: Record<string, string> = { stl: ".stl", step: ".step", "3mf": ".3mf", glb: ".glb", view: ".view.json", py: ".py" };
