"use client";

import { useQuery } from "@tanstack/react-query";
import { Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";
import { REVIEW, review } from "@/lib/api-review";
import { useCapabilities } from "@/lib/capabilities";
import { waitingCount } from "@/lib/review";
import { cn } from "@/lib/utils";
import { Button } from "../ui/button";
import { ThemeToggle } from "../theme-toggle";
import { ApiHealth } from "./api-health";
import { Logo } from "./logo";
import { ModeBanner } from "./mode-banner";

/** Main nav: kept short on purpose. Everything else lives in the footer (site-footer.tsx). "Fix a part" is the CTA button. */
export const NAV = [
  { href: "/parts", label: "Parts" },
  { href: "/how", label: "How it works" },
  { href: "/review", label: "Review" },
  { href: "/agents", label: "For developers" },
] as const;

/** Parts waiting for a person's review, shown next to the nav link; only when this API serves the review queue. */
function ReviewCount() {
  const caps = useCapabilities();
  const q = useQuery({ queryKey: ["review", "queue"], queryFn: () => review.queue(true), enabled: caps.has("get", REVIEW.queue), staleTime: 30_000, retry: false });
  const n = q.data ? waitingCount(q.data.items) : 0;
  if (!n) return null;
  return (
    <span className="ml-1 inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-accent-soft px-1 font-mono text-[10px] text-accent-text tnum">
      {n}
      <span className="sr-only"> waiting</span>
    </span>
  );
}

export function SiteHeader() {
  const pathname = usePathname();
  const menu = React.useRef<HTMLDialogElement>(null);
  const wide = /^\/jobs\/(?!demo$)[^/]+$/.test(pathname);
  const active = (href: string) => pathname === href || pathname.startsWith(`${href}/`);
  return (
    <header className="sticky top-0 z-40">
      <div className="border-b border-border bg-bg/95 backdrop-blur-md supports-[backdrop-filter]:bg-bg/90">
        <div className={cn("mx-auto flex h-14 items-center gap-6 px-4 sm:px-6", wide ? "max-w-none" : "max-w-[1200px]")}>
          <Link href="/" aria-label="PartSmith home" className="rounded-md">
            <Logo />
          </Link>
          <nav aria-label="Main" className="hidden items-center gap-0.5 md:flex">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                aria-current={active(n.href) ? "page" : undefined}
                className={cn(
                  "rounded-md px-2.5 py-1.5 text-[13px] font-medium text-muted transition-colors hover:text-fg",
                  active(n.href) && "text-fg",
                )}
              >
                {n.label}
                {n.href === "/review" ? <ReviewCount /> : null}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <ApiHealth />
            <ThemeToggle className="hidden sm:inline-flex" />
            <Button asChild variant="primary" size="sm">
              <Link href="/fix" aria-current={active("/fix") ? "page" : undefined}>
                Fix a part
              </Link>
            </Button>
            <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open menu" aria-haspopup="dialog" onClick={() => menu.current?.showModal()}>
              <Menu aria-hidden />
            </Button>
            {/* Native modal dialog: focus trap, Esc to close and inert background come from the browser. */}
            <dialog
              ref={menu}
              aria-label="Menu"
              onClick={(e) => e.target === e.currentTarget && menu.current?.close()}
              className="fixed inset-y-0 right-0 left-auto m-0 h-dvh max-h-dvh w-[min(320px,100vw)] max-w-none border-l border-border bg-surface p-5 text-fg shadow-lg backdrop:bg-black/40"
            >
              <div className="flex items-center justify-between">
                <Logo />
                <button
                  type="button"
                  onClick={() => menu.current?.close()}
                  aria-label="Close menu"
                  className="inline-flex size-8 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg"
                >
                  <X className="size-4" aria-hidden />
                </button>
              </div>
              <nav aria-label="Mobile" className="mt-6 flex flex-col">
                {[{ href: "/fix", label: "Fix a part" }, ...NAV, { href: "/jobs/demo", label: "Try a sample" }].map((n) => (
                  <Link
                    key={n.href}
                    href={n.href}
                    prefetch={false}
                    onClick={() => menu.current?.close()}
                    aria-current={active(n.href) ? "page" : undefined}
                    className={cn("border-b border-border py-3 text-[15px] font-medium text-muted hover:text-fg", active(n.href) && "text-fg")}
                  >
                    {n.label}
                    {n.href === "/review" ? <ReviewCount /> : null}
                  </Link>
                ))}
              </nav>
              <p className="mt-4 text-[13px] leading-5 text-subtle">Accuracy, models, the judge path and more are at the bottom of every page.</p>
              <div className="mt-6 flex items-center justify-between">
                <span className="text-[13px] text-muted">Theme</span>
                <ThemeToggle />
              </div>
            </dialog>
          </div>
        </div>
      </div>
      <ModeBanner wide={wide} />
    </header>
  );
}
