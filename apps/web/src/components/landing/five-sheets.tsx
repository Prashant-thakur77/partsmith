"use client";

/**
 * "Five steps" (one landing sheet): the pipeline as a scroll story. On wide screens the figure stays put on the left and changes as each
 * step scrolls past on the right; on phones each step carries its own figure. The photo, outline, dimensions, program
 * lines and the verifier's gap all come from one stored run (labelled); the mat and the sweep are pictures only.
 */
import * as React from "react";
import { artifactUrl } from "@/lib/api";
import { fmtNum } from "@/lib/format";
import { knobLines, measuredValue, measureLinks, type FigureData } from "@/lib/figure-run";
import { useCountUp, useInView, usePrefersReducedMotion } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { LatchGlyph, MAT_H, MAT_W, MatScreen, PartOnMat } from "../art/mat-figure";
import { useSvgId } from "../art/primitives";
import { VerifyOverlay } from "../art/verify-overlay";
import { ErrorState } from "../ui/error-state";
import { useStoredRun } from "./use-figure-run";

type Key = "mat" | "photo" | "mm" | "code" | "verify";

const STEPS: { key: Key; title: string; body: string }[] = [
  {
    key: "mat",
    title: "Your screen becomes the ruler",
    body: "Match a bank card on screen once. PartSmith then draws a ring of markers at true size on your laptop or tablet. No printer, no caliper.",
  },
  {
    key: "photo",
    title: "Lay the part on it and take a photo",
    body: "One photo from above, one from the side if you can. Quick checks ask for a retake when markers are hidden, the photo is blurred or tilted.",
  },
  {
    key: "mm",
    title: "The photo becomes millimetres",
    body: "Code finds the markers and flattens the photo; an image model traces the outline. Every length from here on is measured by code, in millimetres.",
  },
  {
    key: "code",
    title: "An agent writes the part as a program",
    body: "Not a frozen mesh: a short CadQuery program with named, typed knobs. Each measured size sets the knob it belongs to.",
  },
  {
    key: "verify",
    title: "Code checks it against the photo",
    body: "The verifier lays the model's outline over the photo and measures the biggest gap. Too big, and the agent gets the numbers back and tries again. Only this check can say verified.",
  },
];

function Frame({ children, caption, className, panelRef }: { children: React.ReactNode; caption: React.ReactNode; className?: string; panelRef?: React.Ref<HTMLElement> }) {
  return (
    <figure ref={panelRef} className={cn("space-y-2", className)}>
      {children}
      <figcaption className="font-mono text-[11px] leading-4 text-subtle">{caption}</figcaption>
    </figure>
  );
}

function MatPanel({ active }: { active: boolean }) {
  const uid = useSvgId("s1");
  return (
    <Frame caption="Fig. 2 · the screen mat (picture). Markers at true size, from your screen's calibration.">
      <svg viewBox={`0 0 ${MAT_W} ${MAT_H}`} className="h-auto w-full" aria-hidden>
        <MatScreen uid={uid} lit={active}>
          <LatchGlyph />
        </MatScreen>
      </svg>
    </Frame>
  );
}

function PhotoPanel({ fig, active }: { fig: FigureData | null; active: boolean }) {
  const src = artifactUrl(fig?.photo);
  return (
    <Frame caption={fig ? "Fig. 3 · the top photo from the recorded run; the sweep stands for the outline being traced." : "Fig. 3 · loading the recorded run's photo…"}>
      <div className="relative aspect-[8/5] overflow-hidden rounded-[14px] border border-ink/70 bg-surface-2">
        {src ? (
          // eslint-disable-next-line @next/next/no-img-element -- API blob of unknown size
          <img src={src} alt="Top photo of the part lying on the screen mat (recorded run)" loading="lazy" decoding="async" className="absolute inset-0 h-full w-full object-cover" />
        ) : null}
        {active ? (
          <div key={String(active)} aria-hidden className="absolute inset-0 motion-safe:animate-[sweep_1400ms_var(--ease-draft)_both]">
            <div className="absolute inset-0 bg-[linear-gradient(90deg,transparent_70%,color-mix(in_oklch,var(--accent)_22%,transparent))]" />
            <div className="absolute inset-y-0 right-0 w-px bg-dim shadow-[0_0_12px_var(--dim)]" />
          </div>
        ) : null}
      </div>
    </Frame>
  );
}

/**
 * Phones show each step's own figure inline, so it starts when the figure itself is on screen (not when the step's
 * text crosses the middle); on screen at load it shows its finished state at once.
 */
function usePanelStart(active: boolean, self: boolean): { ref: React.RefObject<HTMLElement | null>; go: boolean; instant: boolean } {
  const { ref, seen, atMount } = useInView<HTMLElement>({ threshold: 0.3 });
  return { ref, go: self ? seen || active : active, instant: self && atMount };
}

function MmPanel({ fig, active, self = false }: { fig: FigureData | null; active: boolean; self?: boolean }) {
  const uid = useSvgId("s3");
  const { ref, go, instant } = usePanelStart(active, self);
  active = go;
  const len = useCountUp(fig?.lengthMm != null ? `${fmtNum(fig.lengthMm)} mm` : null, active, undefined, instant);
  const wid = useCountUp(fig?.widthMm != null ? `${fmtNum(fig.widthMm)} mm` : null, active, undefined, instant);
  const hole = useCountUp(fig?.holes[0] ? `Ø ${fmtNum(fig.holes[0].diameterMm)} mm` : null, active, undefined, instant);
  return (
    <Frame panelRef={ref} caption={fig ? "Fig. 4 · the measured outline and sizes from the recorded run (code, from pixels on the mat)." : "Fig. 4 · loading…"}>
      <svg viewBox={`0 0 ${MAT_W} ${MAT_H}`} className="h-auto w-full" role="img" aria-label={fig ? `Measured outline: ${fig.lengthMm != null ? fmtNum(fig.lengthMm) : "—"} by ${fig.widthMm != null ? fmtNum(fig.widthMm) : "—"} millimetres.` : "Loading the measured outline."}>
        <MatScreen uid={uid}>{fig && fig.outline.length > 2 ? <PartOnMat uid={uid} part={fig} labels={{ length: len, width: wid, hole }} drawn={active} dims={active} /> : null}</MatScreen>
      </svg>
    </Frame>
  );
}

function CodePanel({ fig, active, self = false }: { fig: FigureData | null; active: boolean; self?: boolean }) {
  const { ref, go, instant } = usePanelStart(active, self);
  active = go;
  const reduced = usePrefersReducedMotion() || instant;
  const names = React.useMemo(() => fig?.params.map((p) => p.name) ?? [], [fig]);
  const lines = React.useMemo(() => knobLines(fig?.code ?? null, names, 9), [fig, names]);
  const links = React.useMemo(() => (fig ? measureLinks(fig.code).map((l) => ({ ...l, mm: measuredValue(fig, l.measure) })).filter((l) => l.mm != null).slice(0, 3) : []), [fig]);
  const [n, setN] = React.useState(0);
  React.useEffect(() => {
    if (reduced) return setN(lines.length);
    if (!active) return;
    setN(0);
    const t = setInterval(() => setN((x) => (x >= lines.length ? (clearInterval(t), x) : x + 1)), 110);
    return () => clearInterval(t);
  }, [active, reduced, lines.length]);
  const linked = new Set(links.map((l) => l.knob));
  return (
    <Frame panelRef={ref} caption={fig ? "Fig. 5 · lines from the recorded run's part program; each measured size sets the knob it names." : "Fig. 5 · loading…"}>
      <div className="overflow-hidden rounded-[14px] border border-ink/70 bg-surface">
        <div className="flex items-center justify-between border-b border-border px-3 py-1.5 font-mono text-[10.5px] text-subtle">
          <span>part.py</span>
          <span>CadQuery · typed knobs</span>
        </div>
        <pre className="min-h-[200px] overflow-hidden px-3 py-2.5 font-mono text-[11.5px] leading-[1.6] text-muted sm:text-[12px]">
          {lines.map((l, i) => (
            <div key={i} className={cn("truncate whitespace-pre transition-opacity duration-[var(--dur-state)]", i < n ? "opacity-100" : "opacity-0")}>
              {l.knob ? (
                <>
                  {l.text.slice(0, l.text.indexOf(l.knob))}
                  <span className={cn("rounded-[2px]", linked.has(l.knob) ? "bg-dim-soft font-semibold text-dim" : "text-fg")}>{l.knob}</span>
                  {l.text.slice(l.text.indexOf(l.knob) + l.knob.length)}
                </>
              ) : (
                l.text || " "
              )}
              {i === n - 1 && n < lines.length ? <span className="ml-0.5 inline-block h-3.5 w-1.5 translate-y-0.5 bg-accent motion-safe:animate-[caret_900ms_steps(1)_infinite]" aria-hidden /> : null}
            </div>
          ))}
        </pre>
        {links.length ? (
          <ul className="flex flex-wrap gap-1.5 border-t border-border px-3 py-2.5" aria-label="Measured sizes and the knobs they set">
            {links.map((l) => (
              <li key={l.measure} className="inline-flex items-center gap-1.5 rounded-full border border-dim/40 bg-dim-soft px-2 py-0.5 font-mono text-[11px] text-dim">
                <span className="text-fg tnum">{l.measure.includes("diameter") ? "Ø " : ""}{fmtNum(l.mm!)} mm</span>
                <span aria-hidden>→</span>
                <span className="font-semibold">{l.knob}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </Frame>
  );
}

function VerifyPanel({ fig, active }: { fig: FigureData | null; active: boolean }) {
  const ok = fig && fig.outline.length > 2 && fig.worst && fig.limitMm != null;
  return (
    <Frame caption={ok ? "Fig. 6 · the verifier's worst point and gap from the recorded run; the model outline is drawn offset by that gap." : "Fig. 6 · this run has no stored worst point."}>
      {ok ? (
        <VerifyOverlay outline={fig.outline} worst={fig.worst!.at} gapMm={fig.worst!.gapMm} limitMm={fig.limitMm!} passed={fig.worst!.gapMm <= fig.limitMm!} drawn={active} />
      ) : (
        <div className="aspect-[8/5] rounded-[14px] border border-dashed border-border-strong bg-surface-2" />
      )}
    </Frame>
  );
}

function Panel({ k, fig, active, self = false }: { k: Key; fig: FigureData | null; active: boolean; self?: boolean }) {
  if (k === "mat") return <MatPanel active={active} />;
  if (k === "photo") return <PhotoPanel fig={fig} active={active} />;
  if (k === "mm") return <MmPanel fig={fig} active={active} self={self} />;
  if (k === "code") return <CodePanel fig={fig} active={active} self={self} />;
  return <VerifyPanel fig={fig} active={active} />;
}

export function FiveSheets() {
  const { fig, state, replays, job } = useStoredRun("figure");
  const reduced = usePrefersReducedMotion();
  const [active, setActive] = React.useState(0);
  const refs = React.useRef<(HTMLLIElement | null)[]>([]);
  const [seen, setSeen] = React.useState<Set<number>>(() => new Set());

  React.useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (!e.isIntersecting) continue;
          const i = refs.current.indexOf(e.target as HTMLLIElement);
          if (i >= 0) {
            setActive(i);
            setSeen((s) => (s.has(i) ? s : new Set(s).add(i)));
          }
        }
      },
      { rootMargin: "-42% 0px -42% 0px" },
    );
    refs.current.forEach((el) => el && io.observe(el));
    return () => io.disconnect();
  }, []);

  return (
    <>
    {state === "error" ? <ErrorState error={replays.error ?? job.error} compact what="the recorded run" className="mb-6" /> : null}
    <div className="grid grid-cols-1 gap-10 lg:grid-cols-[minmax(0,1.12fr)_minmax(0,1fr)] lg:gap-14">
      <div className="hidden lg:block">
        <div className="sticky top-[max(7rem,calc(50vh-14.5rem))]">
          <div className="relative">
            {STEPS.map((s, i) => (
              <div
                key={s.key}
                aria-hidden={i !== active}
                className={cn(
                  "transition-opacity ease-[var(--ease-out)]",
                  reduced ? "duration-[120ms]" : "duration-[var(--dur-enter)]",
                  i === 0 ? "relative" : "absolute inset-x-0 top-0",
                  i === active ? "opacity-100" : "pointer-events-none opacity-0",
                )}
              >
                <Panel k={s.key} fig={fig} active={i === active} />
              </div>
            ))}
          </div>
          <ol className="mt-5 flex gap-1.5" aria-hidden>
            {STEPS.map((s, i) => (
              <li key={s.key} className={cn("h-1 flex-1 rounded-full transition-colors duration-[var(--dur-state)]", i <= active ? "bg-accent" : "bg-border")} />
            ))}
          </ol>
        </div>
      </div>
      <ol className="space-y-14 lg:space-y-0">
        {STEPS.map((s, i) => (
          <li
            key={s.key}
            ref={(el) => {
              refs.current[i] = el;
            }}
            className="flex flex-col justify-center gap-5 lg:min-h-[68vh]"
          >
            <div className="lg:hidden">
              <Panel k={s.key} fig={fig} active={seen.has(i)} self />
            </div>
            <div className="space-y-3 lg:max-w-md">
              <div className={cn("flex items-center gap-3 font-mono text-[11px] tracking-[0.14em] uppercase transition-colors duration-[var(--dur-state)]", i === active ? "text-accent-text" : "text-accent-text lg:text-subtle")}>
                <span className="flex size-7 items-center justify-center rounded-full border border-current/40 text-[11px] tnum">{i + 1}</span>
                Step {i + 1} of {STEPS.length}
              </div>
              <h3 className={cn("text-[22px] leading-tight font-semibold tracking-[-0.02em] transition-colors duration-[var(--dur-state)] sm:text-[26px]", i === active ? "text-fg" : "text-fg lg:text-muted")}>{s.title}</h3>
              <p className={cn("text-[15px] leading-7 transition-colors duration-[var(--dur-state)]", i === active ? "text-muted" : "text-muted lg:text-subtle")}>{s.body}</p>
            </div>
          </li>
        ))}
      </ol>
    </div>
    </>
  );
}
