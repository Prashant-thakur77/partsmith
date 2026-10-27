"use client";

import { Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";
import { cn } from "@/lib/utils";
import { Button } from "../ui/button";
import { ThemeToggle } from "../theme-toggle";
import { ApiHealth } from "./api-health";
import { Logo } from "./logo";
import { ModeBanner } from "./mode-banner";

export const NAV = [
  { href: "/fix", label: "Fix a part" },
  { href: "/parts", label: "Parts" },
  { href: "/agents", label: "For agents" },
  { href: "/results", label: "Results" },
  { href: "/factory", label: "Factory" },
  { href: "/models", label: "Models" },
  { href: "/judges", label: "Judges" },
] as const;

export function SiteHeader() {
  const pathname = usePathname();
  const menu = React.useRef<HTMLDialogElement>(null);
  const wide = /^\/jobs\/(?!demo$)[^/]+$/.test(pathname);
  const active = (href: string) => pathname === href || pathname.startsWith(`${href}/`);
  return (
    <header className="sticky top-0 z-40">
      <div className="border-b border-border bg-bg/85 backdrop-blur-md supports-[backdrop-filter]:bg-bg/75">
        <div className={cn("mx-auto flex h-14 items-center gap-6 px-4 sm:px-6", wide ? "max-w-none" : "max-w-[1200px]")}>
          <Link href="/" aria-label="PartSmith home" className="rounded-md">
            <Logo />
          </Link>
          <nav aria-label="Main" className="hidden items-center gap-0.5 lg:flex">
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
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <ApiHealth />
            <ThemeToggle className="hidden sm:inline-flex" />
            <Button asChild variant="primary" size="sm" className="hidden sm:inline-flex">
              <Link href="/fix">Fix a broken part</Link>
            </Button>
            <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open menu" aria-haspopup="dialog" onClick={() => menu.current?.showModal()}>
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
                {[...NAV, { href: "/requests", label: "Requests" }, { href: "/lessons", label: "Lessons" }, { href: "/shop", label: "Repair shops" }, { href: "/calibrate", label: "Calibrate screen" }].map((n) => (
                  <Link
                    key={n.href}
                    href={n.href}
                    prefetch={false}
                    onClick={() => menu.current?.close()}
                    aria-current={active(n.href) ? "page" : undefined}
                    className={cn("border-b border-border py-3 text-[15px] font-medium text-muted hover:text-fg", active(n.href) && "text-fg")}
                  >
                    {n.label}
                  </Link>
                ))}
              </nav>
              <div className="mt-6 flex items-center justify-between">
                <span className="text-[13px] text-muted">Theme</span>
                <ThemeToggle />
              </div>
              <Button asChild variant="primary" className="mt-6 w-full">
                <Link href="/fix" onClick={() => menu.current?.close()}>
                  Fix a broken part
                </Link>
              </Button>
            </dialog>
          </div>
        </div>
      </div>
      <ModeBanner wide={wide} />
    </header>
  );
}
