"use client";

import { ArrowRight, BookOpen, X } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { cn } from "@/lib/utils";
import { Button } from "../ui/button";

export const GUIDE_KEY = "partsmith.fix-guide.dismissed.v1";
/** `<html data-fix-guide="hidden">` is set before first paint by GUIDE_SCRIPT so the server can render both states. */
const GUIDE_ATTR = "fixGuide";
const GUIDE_SCRIPT = `try{if(localStorage.getItem(${JSON.stringify(GUIDE_KEY)})==="1")document.documentElement.dataset.${GUIDE_ATTR}="hidden"}catch(e){}`;

function readDismissed(): boolean {
  try {
    return window.localStorage.getItem(GUIDE_KEY) === "1";
  } catch {
    return false; // storage blocked: show the guide, it is only a guide
  }
}

function writeDismissed(v: boolean): void {
  try {
    if (v) window.localStorage.setItem(GUIDE_KEY, "1");
    else window.localStorage.removeItem(GUIDE_KEY);
  } catch {
    /* storage blocked: the choice lasts for this page view */
  }
  if (v) document.documentElement.dataset[GUIDE_ATTR] = "hidden";
  else delete document.documentElement.dataset[GUIDE_ATTR];
}

/** Step 1: hold a bank card against the screen and match the on-screen outline (sets the screen's mm scale). */
function CardArt() {
  return (
    <svg viewBox="0 0 160 100" className="h-full w-full" aria-hidden>
      <rect x="14" y="8" width="132" height="76" rx="5" className="fill-surface stroke-border-strong" strokeWidth="2" />
      <rect x="66" y="86" width="28" height="6" rx="2" className="fill-border-strong" />
      <rect x="46" y="26" width="68" height="43" rx="4" className="fill-none stroke-accent" strokeWidth="1.5" strokeDasharray="4 3" />
      <g transform="translate(52 31) rotate(-4)">
        <rect width="62" height="39" rx="4" className="fill-accent-soft stroke-accent" strokeWidth="1.5" />
        <rect x="7" y="9" width="11" height="8" rx="1.5" className="fill-accent/40" />
        <rect x="7" y="27" width="30" height="3" rx="1.5" className="fill-accent/40" />
      </g>
      <path d="M46 76h68" className="stroke-muted" strokeWidth="1" markerEnd="url(#a)" markerStart="url(#a)" />
      <defs>
        <marker id="a" viewBox="0 0 6 6" refX="3" refY="3" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M0 0L6 3L0 6z" className="fill-muted" />
        </marker>
      </defs>
    </svg>
  );
}

/** Step 2: the screen lies flat showing the mat; the part sits in the middle, clear of the corner markers. */
function MatArt() {
  const marker = (x: number, y: number) => (
    <g key={`${x}-${y}`} transform={`translate(${x} ${y})`}>
      <rect width="14" height="14" className="fill-fg" />
      <rect x="3" y="3" width="4" height="4" className="fill-surface" />
      <rect x="7" y="7" width="4" height="4" className="fill-surface" />
    </g>
  );
  return (
    <svg viewBox="0 0 160 100" className="h-full w-full" aria-hidden>
      <path d="M22 18h116l14 70H8z" className="fill-surface stroke-border-strong" strokeWidth="2" strokeLinejoin="round" />
      {[marker(28, 24), marker(118, 24), marker(20, 66), marker(126, 66)]}
      <g transform="translate(58 44)">
        <rect width="46" height="22" rx="5" className="fill-accent-soft stroke-accent" strokeWidth="1.5" />
        <circle cx="10" cy="11" r="3.5" className="fill-surface stroke-accent" strokeWidth="1.2" />
        <circle cx="36" cy="11" r="3.5" className="fill-surface stroke-accent" strokeWidth="1.2" />
      </g>
    </svg>
  );
}

/** Step 3: the phone straight above the part, the lens looking down, the whole mat in frame. */
function PhoneArt() {
  return (
    <svg viewBox="0 0 160 100" className="h-full w-full" aria-hidden>
      <path d="M22 70h116l10 22H12z" className="fill-surface stroke-border-strong" strokeWidth="2" strokeLinejoin="round" />
      <rect x="62" y="74" width="36" height="10" rx="3" className="fill-accent-soft stroke-accent" strokeWidth="1.2" />
      <rect x="56" y="6" width="48" height="12" rx="3" className="fill-surface stroke-fg" strokeWidth="2" />
      <circle cx="80" cy="18" r="2.5" className="fill-fg" />
      <path d="M80 22v46" className="stroke-accent" strokeWidth="1.5" strokeDasharray="3 3" />
      <path d="M64 21L28 68M96 21l36 47" className="stroke-muted" strokeWidth="1" strokeDasharray="2 3" />
      <path d="M86 64h8v-8" className="fill-none stroke-accent" strokeWidth="1.2" />
    </svg>
  );
}

const STEPS = [
  { title: "Calibrate the screen with a card", body: "Hold any bank or ID card against the screen and match the outline. That tells PartSmith how big a millimetre is on this screen.", art: CardArt, href: "/calibrate", link: "Calibrate now" },
  { title: "Lay the part on the screen mat", body: "Open the mat full screen, lay the screen flat and put the part in the middle, clear of the black corner squares.", art: MatArt, href: "/mat", link: "Open the mat" },
  { title: "Take the photo from straight above", body: "Hold the phone flat over the part so all four corner squares are in the picture. No flash; soft light is best.", art: PhoneArt, href: null, link: null },
] as const;

/**
 * First visit to /fix: three illustrated steps, dismissed once and remembered on this device (localStorage, guarded:
 * blocked storage just shows it again). Always offers the way out for people with no part in hand: /describe.
 *
 * No layout shift: before hydration both states are in the HTML and a tiny inline script flags `<html>` from
 * localStorage before first paint, so CSS shows the right one; after hydration React renders only that one.
 */
export function FirstVisitGuide({ className }: { className?: string }) {
  const [dismissed, setDismissed] = React.useState<boolean | null>(null);
  React.useEffect(() => setDismissed(readDismissed()), []);
  const set = (v: boolean) => {
    writeDismissed(v);
    setDismissed(v);
  };
  const describe = (
    <Link href="/describe" className="inline-flex items-center gap-1 text-[13px] font-medium text-accent-text hover:underline">
      No part in hand? Describe it <ArrowRight className="size-3.5" aria-hidden />
    </Link>
  );
  const collapsed = (extra?: string) => (
      <div className={cn("flex flex-wrap items-center justify-between gap-3", extra, className)}>
        <button type="button" onClick={() => set(false)} className="inline-flex items-center gap-1.5 text-[13px] text-muted hover:text-fg">
          <BookOpen className="size-3.5" aria-hidden /> Show the 3-step guide
        </button>
        {describe}
      </div>
  );
  const full = (extra?: string) => (
    <section aria-labelledby="fix-guide-title" className={cn("rounded-xl border border-border bg-surface p-4 sm:p-5", extra, className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-0.5">
          <h2 id="fix-guide-title" className="text-[16px] font-semibold tracking-tight">
            First time? Three steps to a measured part
          </h2>
          <p className="text-[13px] text-muted">The screen mat is the ruler: every millimetre comes from it, so these steps matter.</p>
        </div>
        <Button variant="ghost" size="icon-sm" aria-label="Hide the guide" title="Hide the guide" onClick={() => set(true)}>
          <X aria-hidden />
        </Button>
      </div>
      <ol className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
        {STEPS.map((s, i) => (
          <li key={s.title} className="flex flex-col overflow-hidden rounded-lg border border-border bg-surface-2">
            <div className="h-28 border-b border-border bg-bg/40 p-2">
              <s.art />
            </div>
            <div className="flex flex-1 flex-col gap-1 p-3">
              <h3 className="text-[13.5px] font-semibold">
                <span className="mr-1.5 font-mono text-[12px] text-subtle">{i + 1}</span>
                {s.title}
              </h3>
              <p className="text-[12.5px] leading-5 text-muted">{s.body}</p>
              {s.href ? (
                <Link href={s.href} className="mt-auto pt-1 text-[12.5px] font-medium text-accent-text hover:underline">
                  {s.link}
                </Link>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        {describe}
        <Button variant="outline" size="sm" onClick={() => set(true)}>
          Got it
        </Button>
      </div>
    </section>
  );
  if (dismissed === null) {
    return (
      <>
        <script dangerouslySetInnerHTML={{ __html: GUIDE_SCRIPT }} />
        {full("[html[data-fix-guide=hidden]_&]:hidden")}
        {collapsed("[html:not([data-fix-guide=hidden])_&]:hidden")}
      </>
    );
  }
  return dismissed ? collapsed() : full();
}
