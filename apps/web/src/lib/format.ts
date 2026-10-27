/** Formatting helpers. Lengths are millimetres everywhere; unit strings are always shown. */

export function fmtNum(v: number, decimals = 2): string {
  if (!Number.isFinite(v)) return "—";
  return v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export function fmtMm(v: number | null | undefined, decimals = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `${fmtNum(v, decimals)} mm`;
}

export function fmtSigned(v: number, decimals = 2): string {
  if (!Number.isFinite(v)) return "—";
  const s = fmtNum(Math.abs(v), decimals);
  return v > 0 ? `+${s}` : v < 0 ? `−${s}` : s;
}

export function fmtUsd(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  if (v === 0) return "$0";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(v < 1 ? 3 : 2)}`;
}

export function fmtInt(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return Math.round(v).toLocaleString("en-US");
}

export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)} s`;
}

export function fmtPct(v: number | null | undefined, decimals = 1): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(decimals)} %`;
}

/** Unix seconds (API) → relative time. */
export function timeAgo(tsSeconds: number, now = Date.now()): string {
  const d = Math.max(0, now / 1000 - tsSeconds);
  if (d < 45) return "just now";
  if (d < 3600) return `${Math.round(d / 60)} min ago`;
  if (d < 86400) return `${Math.round(d / 3600)} h ago`;
  return `${Math.round(d / 86400)} d ago`;
}

export function fmtDate(tsSeconds: number): string {
  return new Date(tsSeconds * 1000).toLocaleString("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function shortSha(sha: string | null | undefined, n = 8): string {
  if (!sha) return "—";
  return sha.replace(/^sha256:/, "").slice(0, n);
}

export function titleCase(s: string): string {
  return s.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function paramLabel(name: string, label?: string): string {
  return label && label.trim() ? label : titleCase(name.replace(/_mm$|_deg$/, ""));
}
