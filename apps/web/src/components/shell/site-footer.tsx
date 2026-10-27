import Link from "next/link";
import { Logo } from "./logo";

const COLS = [
  {
    title: "Product",
    links: [
      { href: "/fix", label: "Fix a part" },
      { href: "/parts", label: "Registry" },
      { href: "/mat", label: "Screen mat" },
      { href: "/calibrate", label: "Calibrate screen" },
      { href: "/jobs", label: "Recent jobs" },
    ],
  },
  {
    title: "Developers",
    links: [
      { href: "/agents", label: "REST + MCP" },
      { href: "/llms.txt", label: "llms.txt" },
      { href: "/prompt.txt", label: "prompt.txt" },
      { href: "/api/v1/openapi.json", label: "OpenAPI" },
    ],
  },
  {
    title: "Proof",
    links: [
      { href: "/bench", label: "Bench results" },
      { href: "/status", label: "Model status" },
      { href: "/judges", label: "Judge path" },
      { href: "/steer", label: "Steer factory" },
    ],
  },
] as const;

export function SiteFooter() {
  return (
    <footer className="mt-24 border-t border-border bg-surface">
      <div className="mx-auto grid max-w-[1200px] gap-10 px-4 py-12 sm:px-6 md:grid-cols-[1.4fr_repeat(3,1fr)]">
        <div className="space-y-3">
          <Logo />
          <p className="max-w-xs text-[13px] leading-5 text-muted">
            Photos of a broken plastic part in, a measured and verified parametric replacement out. The model proposes; code
            decides.
          </p>
        </div>
        {COLS.map((c) => (
          <div key={c.title}>
            <h2 className="text-[11px] font-medium uppercase tracking-[0.08em] text-subtle">{c.title}</h2>
            <ul className="mt-3 space-y-2">
              {c.links.map((l) => (
                <li key={l.href}>
                  {/\.(txt|json)$/.test(l.href) ? (
                    <a href={l.href} className="text-[13px] text-muted hover:text-fg">
                      {l.label}
                    </a>
                  ) : (
                    <Link href={l.href} prefetch={false} className="text-[13px] text-muted hover:text-fg">
                      {l.label}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="border-t border-border">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-2 px-4 py-4 text-[12px] text-subtle sm:px-6">
          <span>All lengths in millimetres. Every number on screen comes from the API.</span>
          <span className="font-mono">units: mm · angles: deg</span>
        </div>
      </div>
    </footer>
  );
}
