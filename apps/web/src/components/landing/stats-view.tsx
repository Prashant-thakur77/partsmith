import type { Stats } from "@/lib/api-types";
import { fmtInt, fmtNum } from "@/lib/format";
import { Skeleton } from "../ui/skeleton";

/** Counters computed by the API from the database (`/stats`). Dashes when the API is offline — never placeholders. */
export function StatsView({ stats: s, state }: { stats?: Stats; state: "pending" | "error" | "ok" }) {
  const items = [
    { label: "verified parts", value: s ? fmtInt(s.verified) : null, sub: s ? `of ${fmtInt(s.parts)} in the registry` : null },
    { label: "from real photos", value: s ? fmtInt(s.real) : null, sub: s ? `${fmtInt(s.synthetic)} synthetic, labelled` : null },
    { label: "fix jobs run", value: s ? fmtInt(s.jobs) : null, sub: "every run logged" },
    { label: "grams of PLA", value: s ? fmtNum(s.grams_pla, 0) : null, sub: "to print every part once" },
  ];
  return (
    <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border md:grid-cols-4">
      {items.map((it) => (
        <div key={it.label} className="space-y-1.5 bg-surface p-5">
          <dt className="text-[12px] text-muted">{it.label}</dt>
          <dd className="font-mono text-[28px] leading-none font-medium tracking-tight text-fg tnum">
            {state === "pending" ? <Skeleton className="h-7 w-16" /> : (it.value ?? "—")}
          </dd>
          <dd className="text-[12px] text-subtle">{state === "error" ? "API offline" : (it.sub ?? "\u00a0")}</dd>
        </div>
      ))}
    </dl>
  );
}
