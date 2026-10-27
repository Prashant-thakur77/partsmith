"use client";

import { Menu } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";
import { cn } from "@/lib/utils";
import { Button } from "../ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "../ui/sheet";
import { ThemeToggle } from "../theme-toggle";
import { ApiHealth } from "./api-health";
import { Logo } from "./logo";
import { ModeBanner } from "./mode-banner";

export const NAV = [
  { href: "/fix", label: "Fix a part" },
  { href: "/parts", label: "Registry" },
  { href: "/agents", label: "For agents" },
  { href: "/bench", label: "Bench" },
  { href: "/steer", label: "Steer" },
  { href: "/status", label: "Status" },
] as const;

export function SiteHeader() {
  const pathname = usePathname();
  const [open, setOpen] = React.useState(false);
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
            <Sheet open={open} onOpenChange={setOpen}>
              <SheetTrigger asChild>
                <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open menu">
                  <Menu aria-hidden />
                </Button>
              </SheetTrigger>
              <SheetContent side="right" className="p-5">
                <SheetTitle className="sr-only">Menu</SheetTitle>
                <SheetDescription className="sr-only">Site navigation</SheetDescription>
                <Logo />
                <nav aria-label="Mobile" className="mt-6 flex flex-col">
                  {[...NAV, { href: "/judges", label: "Judges" }, { href: "/calibrate", label: "Calibrate screen" }].map((n) => (
                    <Link
                      key={n.href}
                      href={n.href}
                      onClick={() => setOpen(false)}
                      aria-current={active(n.href) ? "page" : undefined}
                      className={cn(
                        "border-b border-border py-3 text-[15px] font-medium text-muted hover:text-fg",
                        active(n.href) && "text-fg",
                      )}
                    >
                      {n.label}
                    </Link>
                  ))}
                </nav>
                <div className="mt-6 flex items-center justify-between">
                  <span className="text-[13px] text-muted">Theme</span>
                  <ThemeToggle />
                </div>
                <Button asChild variant="primary" className="mt-6">
                  <Link href="/fix" onClick={() => setOpen(false)}>
                    Fix a broken part
                  </Link>
                </Button>
              </SheetContent>
            </Sheet>
          </div>
        </div>
      </div>
      <ModeBanner wide={wide} />
    </header>
  );
}
