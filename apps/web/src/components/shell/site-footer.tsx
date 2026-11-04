import Link from "next/link";
import { REPO_URL } from "@/lib/site-links";
import { Logo } from "./logo";

const COLS = [
  {
    title: "Product",
    links: [
      { href: "/fix", label: "Fix a part" },
      { href: "/describe", label: "Describe a part" },
      { href: "/playground", label: "Playground" },
      { href: "/parts", label: "Parts" },
      { href: "/requests", label: "Request a part" },
      { href: "/jobs/demo", label: "Try a sample" },
      { href: "/calibrate", label: "Calibrate screen" },
      { href: "/mat", label: "Screen mat" },
    ],
  },
  {
    title: "Proof",
    links: [
      { href: "/how", label: "How it works" },
      { href: "/results", label: "Accuracy" },
      { href: "/models", label: "Which AI did what" },
      { href: "/lessons", label: "What it learned" },
      { href: "/judges", label: "Judge path" },
      { href: "/deck/index.html", label: "Interactive deck" },
    ],
  },
  {
    title: "Labs",
    links: [
      { href: "/factory", label: "Make a part family" },
      { href: "/shop", label: "Repair shops" },
      { href: "/jobs", label: "All jobs" },
      { href: "/admin", label: "Admin" },
    ],
  },
  {
    title: "Developers",
    links: [
      { href: REPO_URL, label: "Source code" },
      { href: "/agents", label: "REST + MCP" },
      { href: "/llms.txt", label: "llms.txt" },
      { href: "/prompt.txt", label: "prompt.txt" },
      { href: "/api/v1/openapi.json", label: "OpenAPI" },
    ],
  },
] as const;

export function SiteFooter() {
  return (
    <footer className="mt-24 border-t border-border bg-surface">
      <div className="mx-auto grid max-w-[1200px] gap-10 px-4 py-12 sm:px-6 grid-cols-2 md:grid-cols-[1.4fr_repeat(4,1fr)]">
        <div className="col-span-2 space-y-3 md:col-span-1">
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
                  {/\.(txt|json|html)$/.test(l.href) || /^https?:/.test(l.href) ? (
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
