"use client";

/**
 * Small accessible tooltip (no positioning library): opens on hover or keyboard focus after a short delay, stays open
 * while hovered (WCAG 1.4.13), closes on Esc, and is rendered `position: fixed` so overflow-hidden parents never clip it.
 * The trigger gets `aria-describedby` while it is open.
 */
import * as React from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

type Side = "top" | "bottom" | "left" | "right";

export function TooltipProvider({ children }: { children: React.ReactNode; delayDuration?: number }) {
  return <>{children}</>;
}

export function Tooltip({
  content,
  children,
  side = "top",
  className,
  delay = 200,
  tap = false,
}: {
  content: React.ReactNode;
  children: React.ReactNode;
  side?: Side;
  className?: string;
  delay?: number;
  /** A touch on the trigger opens and closes it, since a phone has no hover. */
  tap?: boolean;
}) {
  const id = React.useId();
  const anchor = React.useRef<HTMLSpanElement>(null);
  const tip = React.useRef<HTMLDivElement>(null);
  const [open, setOpen] = React.useState(false);
  const [pos, setPos] = React.useState<{ x: number; y: number } | null>(null);
  const timer = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const show = (wait: number) => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setOpen(true), wait);
  };
  const hide = (wait = 80) => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setOpen(false);
      setPos(null);
    }, wait);
  };
  React.useEffect(() => () => clearTimeout(timer.current), []);

  React.useLayoutEffect(() => {
    if (!open || !anchor.current || !tip.current) return;
    const a = anchor.current.getBoundingClientRect();
    const t = tip.current.getBoundingClientRect();
    const gap = 6;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let s = side;
    if (s === "top" && a.top - t.height - gap < 4) s = "bottom";
    else if (s === "bottom" && a.bottom + t.height + gap > vh - 4) s = "top";
    let x = s === "left" ? a.left - t.width - gap : s === "right" ? a.right + gap : a.left + a.width / 2 - t.width / 2;
    let y = s === "top" ? a.top - t.height - gap : s === "bottom" ? a.bottom + gap : a.top + a.height / 2 - t.height / 2;
    x = Math.max(8, Math.min(x, vw - t.width - 8));
    y = Math.max(4, Math.min(y, vh - t.height - 4));
    setPos({ x, y });
  }, [open, side]);

  React.useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && hide(0);
    const onScroll = () => hide(0);
    const onDown = (e: PointerEvent) => {
      const target = e.target as Node;
      if (!anchor.current?.contains(target) && !tip.current?.contains(target)) hide(0);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onScroll, true);
    window.addEventListener("pointerdown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onScroll, true);
      window.removeEventListener("pointerdown", onDown);
    };
  }, [open]);

  const child = React.isValidElement<{ "aria-describedby"?: string }>(children)
    ? React.cloneElement(children, { "aria-describedby": open ? id : undefined })
    : children;

  return (
    <span
      ref={anchor}
      className="inline-flex max-w-full"
      onPointerEnter={(e) => e.pointerType === "mouse" && show(delay)}
      onPointerLeave={(e) => e.pointerType === "mouse" && hide()}
      onPointerUp={(e) => tap && e.pointerType !== "mouse" && setOpen((was) => !was)}
      onFocusCapture={(e) => (e.target as HTMLElement).matches(":focus-visible") && show(0)}
      onBlurCapture={() => hide(0)}
    >
      {child}
      {open
        ? createPortal(
            <div
              ref={tip}
              id={id}
              role="tooltip"
              onPointerEnter={() => clearTimeout(timer.current)}
              onPointerLeave={() => hide()}
              style={{ position: "fixed", left: pos?.x ?? -9999, top: pos?.y ?? -9999 }}
              className={cn(
                "z-[70] w-max max-w-[min(20rem,calc(100vw-1rem))] rounded-md bg-inverse px-2.5 py-1.5 text-xs leading-[1.45] text-inverse-fg shadow-md",
                pos ? "animate-fade-in" : "opacity-0",
                className,
              )}
            >
              {content}
            </div>,
            document.body,
          )
        : null}
    </span>
  );
}
