import { Code2, Gauge, PlayCircle, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { REPO_URL } from "@/lib/site-links";

const STEPS = [
  { href: "#film", icon: PlayCircle, title: "Watch", body: "The story and a real run, in the film" },
  { href: "#try", icon: SlidersHorizontal, title: "Try the knob", body: "Real baked CAD, in your browser" },
  { href: "#proof", icon: Gauge, title: "See the proof", body: "Numbers with their sources" },
  { href: REPO_URL, icon: Code2, title: "Open the code", body: "Everything is in the public repo", external: true },
] as const;

/** One clear way through the page for someone seeing it for the first time. */
export function JudgePath() {
  return (
    <nav aria-label="A way through this page">
      <ol className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        {STEPS.map((s, i) => {
          const inner = (
            <>
              <span className="flex items-center justify-between">
                <span className="inline-flex items-center gap-2 text-[14px] font-semibold">
                  <span className="font-mono text-[11px] text-accent-text tnum">{i + 1}</span> {s.title}
                </span>
                <s.icon className="size-4 text-subtle transition-colors group-hover:text-fg" aria-hidden />
              </span>
              <span className="text-[12.5px] leading-[18px] text-muted">{s.body}</span>
            </>
          );
          const cls =
            "group flex h-full flex-col gap-1 rounded-lg border border-border bg-surface p-3 transition-colors hover:border-border-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring";
          return (
            <li key={s.title}>
              {"external" in s ? (
                <a href={s.href} target="_blank" rel="noreferrer" className={cls}>
                  {inner}
                </a>
              ) : (
                <Link href={s.href} className={cls}>
                  {inner}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
