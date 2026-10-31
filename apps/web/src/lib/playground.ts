/**
 * Pure helpers for the playground, Describe it and Make a variant: knob values ↔ query strings, presets, the
 * program text with the current values written in, and where each value came from.
 *
 * Kept free of runtime imports so `node --test` can load it directly.
 */
import type { ParamSpec } from "./api-types";

/** Snap to the knob's step (relative to min) and clamp to its range; topology knobs are integers. */
export function snapValue(spec: Pick<ParamSpec, "min" | "max" | "step" | "topology">, v: number): number {
  if (!Number.isFinite(v)) return spec.min;
  const c = Math.min(spec.max, Math.max(spec.min, v));
  const stepped = spec.step > 0 ? spec.min + Math.round((c - spec.min) / spec.step) * spec.step : c;
  const out = Math.min(spec.max, Math.max(spec.min, stepped));
  return spec.topology ? Math.round(out) : Number(out.toFixed(6));
}

/** Knob values from a query string: only real knobs, finite numbers, clamped and snapped; everything else is the default. */
export function valuesFromQuery(params: ParamSpec[], query: URLSearchParams | Record<string, string | undefined>): Record<string, number> {
  const get = (k: string) => (query instanceof URLSearchParams ? query.get(k) : query[k]) ?? null;
  const out: Record<string, number> = {};
  for (const p of params) {
    const raw = get(p.name);
    const n = raw === null || raw.trim() === "" ? NaN : Number(raw);
    out[p.name] = Number.isFinite(n) ? snapValue(p, n) : p.default;
  }
  return out;
}

/** Only the knobs that differ from their default (shareable URLs stay short). */
export function changedValues(params: ParamSpec[], values: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const p of params) {
    const v = values[p.name];
    if (v !== undefined && Math.abs(v - p.default) > Math.max(p.step / 2, 1e-9)) out[p.name] = v;
  }
  return out;
}

/** Query string for a playground URL: `t=<template>` plus the changed knobs (sorted, so equal states give equal URLs). */
export function playgroundQuery(template: string, params: ParamSpec[], values: Record<string, number>): string {
  const qs = new URLSearchParams();
  qs.set("t", template);
  const changed = changedValues(params, values);
  for (const k of Object.keys(changed).sort()) qs.set(k, String(changed[k]));
  return qs.toString();
}

/** A preset applied on top of the defaults (presets name only the knobs they change). */
export function applyPreset(params: ParamSpec[], preset: { values: Record<string, number> }): Record<string, number> {
  const out: Record<string, number> = {};
  for (const p of params) out[p.name] = preset.values[p.name] !== undefined ? snapValue(p, preset.values[p.name]!) : p.default;
  return out;
}

/** The preset whose values the knobs currently show exactly (null when the knobs were moved off every preset). */
export function activePreset<T extends { id: string; values: Record<string, number> }>(params: ParamSpec[], values: Record<string, number>, presets: T[]): T | null {
  for (const pr of presets) {
    const want = applyPreset(params, pr);
    if (params.every((p) => Math.abs((values[p.name] ?? p.default) - want[p.name]!) <= Math.max(p.step / 2, 1e-9))) return pr;
  }
  return null;
}

export type ProgramLine = { n: number; text: string; knob: string | null; changed: boolean };

const PARAM_LINE = /^(\s*)"([A-Za-z_][A-Za-z0-9_]*)"\s*:\s*\(\s*(-?\d+(?:\.\d+)?)/;

function fmt(v: number): string {
  return Number.isInteger(v) ? String(v) : String(Number(v.toFixed(4)));
}

/**
 * The program's lines with each PARAMS default rewritten to the current value (as the downloaded part.py has it);
 * `knob` names the knob a line defines and `changed` marks the ones that differ from the template default.
 */
export function programLines(code: string, values: Record<string, number>): ProgramLine[] {
  const lines = code.replace(/\r\n/g, "\n").split("\n");
  let inParams = false;
  return lines.map((text, i) => {
    if (/^PARAMS\s*=\s*\{/.test(text)) inParams = true;
    else if (inParams && /^\}/.test(text)) inParams = false;
    const m = inParams ? PARAM_LINE.exec(text) : null;
    if (!m) return { n: i + 1, text, knob: null, changed: false };
    const name = m[2]!;
    const dflt = Number(m[3]);
    const v = values[name];
    if (v === undefined || !Number.isFinite(v)) return { n: i + 1, text, knob: name, changed: false };
    const changed = Math.abs(v - dflt) > 1e-9;
    const start = m[0].length - m[3]!.length;
    return { n: i + 1, text: text.slice(0, start) + fmt(v) + text.slice(m[0].length), knob: name, changed };
  });
}

export type ValueTag = "you said" | "you answered" | "default" | "inferred" | "changed";

/** Where a knob's value comes from on a Describe result: the person's words, an answer, the template, the model — or
 * "changed" once the knob was moved away from that value on this page. */
export function valueTag(row: { source: "user" | "answer" | "default" | "inferred"; value: number }, current: number | undefined, step: number): ValueTag {
  if (current !== undefined && Math.abs(current - row.value) > Math.max(step / 2, 1e-9)) return "changed";
  return row.source === "user" ? "you said" : row.source === "answer" ? "you answered" : row.source;
}

/** Answers for the describe questions: an empty field means "use the default" (null); anything else must be a number. */
export function parseAnswers(fields: Record<string, string>): { answers: Record<string, number | null>; bad: string[] } {
  const answers: Record<string, number | null> = {};
  const bad: string[] = [];
  for (const [k, raw] of Object.entries(fields)) {
    const t = raw.trim().replace(",", ".").replace(/\s*mm$/i, "");
    if (!t) answers[k] = null;
    else if (Number.isFinite(Number(t))) answers[k] = Number(t);
    else bad.push(k);
  }
  return { answers, bad };
}

/** Print time in words ("6 min", "1 h 05 min"). */
export function minutesText(min: number): string {
  if (!Number.isFinite(min) || min < 0) return "—";
  if (min < 60) return `${Math.max(1, Math.round(min))} min`;
  const h = Math.floor(min / 60);
  return `${h} h ${String(Math.round(min - h * 60)).padStart(2, "0")} min`;
}
