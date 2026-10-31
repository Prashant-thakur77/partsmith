"use client";

/**
 * The site's motion hooks. One rule everywhere: with `prefers-reduced-motion: reduce` the final state is shown at once —
 * no count-ups, no drawing lines, no autoplay. Durations and easings live in globals.css (`--dur-*`, `--ease-*`).
 */
import * as React from "react";
import { countText } from "./count-up";

const REDUCE = "(prefers-reduced-motion: reduce)";

/** True when the visitor asked for less motion. On the server (and the first hydration pass) it is true: final states. */
export function usePrefersReducedMotion(): boolean {
  return React.useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(REDUCE);
      m.addEventListener("change", cb);
      return () => m.removeEventListener("change", cb);
    },
    () => window.matchMedia(REDUCE).matches,
    () => true,
  );
}

/** Marks the document as scripted (CSS hides not-yet-revealed sections only then). Called once by Providers. */
export function useMotionReady() {
  React.useLayoutEffect(() => {
    document.documentElement.dataset.js = "";
  }, []);
}

function inViewport(el: Element, threshold: number): boolean {
  const r = el.getBoundingClientRect();
  const h = window.innerHeight || document.documentElement.clientHeight;
  const visible = Math.min(r.bottom, h) - Math.max(r.top, 0);
  return r.height > 0 ? visible / Math.min(r.height, h) >= threshold : r.top < h && r.bottom >= 0;
}

/**
 * Flag an element once it scrolls into view (threshold 0.2, once). Returns a ref, whether it has been seen, and
 * `atMount`: it was already on screen when the page hydrated (counted as seen before the first paint, so nothing
 * flickers; counters use it to show their final value at once instead of animating from zero).
 */
export function useInView<T extends Element>(opts: { threshold?: number; rootMargin?: string; once?: boolean } = {}) {
  const { threshold = 0.2, rootMargin = "0px", once = true } = opts;
  const ref = React.useRef<T>(null);
  const [seen, setSeen] = React.useState(false);
  const [atMount, setAtMount] = React.useState(false);
  const first = React.useRef(true);
  React.useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const wasFirst = first.current;
    first.current = false;
    if (inViewport(el, threshold)) {
      setSeen(true);
      if (wasFirst) setAtMount(true);
      if (once) return;
    }
    if (typeof IntersectionObserver === "undefined") {
      setSeen(true);
      return;
    }
    const io = new IntersectionObserver(
      ([e]) => {
        if (e?.isIntersecting) {
          setSeen(true);
          if (once) io.disconnect();
        } else if (!once) setSeen(false);
      },
      { threshold, rootMargin },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [threshold, rootMargin, once]);
  return { ref, seen, atMount };
}

/**
 * Reveal-on-scroll for a section: spread the returned props on the element (8 px up + fade, once). Children that should
 * stagger carry `data-reveal` and `style={{ "--reveal-i": i }}` (60 ms each); the root marks them all revealed together.
 */
export function useReveal<T extends HTMLElement>(threshold = 0.2) {
  const ref = React.useRef<T>(null);
  React.useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    // children marked data-reveal follow their revealed ancestor in CSS, including ones rendered later
    const show = () => el.setAttribute("data-revealed", "");
    if (inViewport(el, Math.min(threshold, 0.05)) || typeof IntersectionObserver === "undefined") return show();
    const io = new IntersectionObserver(
      ([e]) => {
        if (e?.isIntersecting) {
          show();
          io.disconnect();
        }
      },
      { threshold },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [threshold]);
  return { ref, "data-reveal": "" } as const;
}

/**
 * Count up once to `text` (an already formatted real value such as "0.10 mm" or "17/17") over `ms`, starting when
 * `start` turns true. Until then it prints the final text (server HTML, no-JS and an off-screen counter alike), so a
 * wrong number is only ever on screen during the short count itself. `skip` (e.g. already on screen when the page
 * loaded) shows the final text without counting. Under reduced motion it never animates. Pair it with an sr-only copy
 * of the final text (CountUp does).
 */
export function useCountUp(text: string | null | undefined, start: boolean, ms = 500, skip = false): string | null {
  const reduced = usePrefersReducedMotion();
  const [out, setOut] = React.useState<string | null>(text ?? null);
  const done = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (text == null) {
      setOut(null);
      return;
    }
    if (reduced || skip || done.current === text || !start) {
      if (skip) done.current = text;
      setOut(text);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - t0) / ms);
      setOut(countText(text, t));
      if (t < 1) raf = requestAnimationFrame(tick);
      else done.current = text;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [text, start, ms, reduced, skip]);
  return out;
}
