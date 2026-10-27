import { cn } from "@/lib/utils";

function MatArt() {
  const sq = [0, 1, 2, 3, 4, 5];
  return (
    <svg viewBox="0 0 200 120" className="h-full w-full" aria-hidden>
      <rect x="20" y="14" width="160" height="92" rx="6" className="fill-surface stroke-border-strong" strokeWidth="1.5" />
      <rect x="28" y="22" width="144" height="76" className="fill-white" />
      {sq.map((i) => (
        <g key={i}>
          <rect x={32 + i * 23.5} y={26} width="10" height="10" fill="#111" />
          <rect x={32 + i * 23.5} y={84} width="10" height="10" fill="#111" />
        </g>
      ))}
      <rect x={32} y={55} width="10" height="10" fill="#111" />
      <rect x={158} y={55} width="10" height="10" fill="#111" />
      <rect x="62" y="44" width="62" height="38" rx="4" className="fill-accent/25 stroke-accent" strokeWidth="1.5" strokeDasharray="4 3" />
      <text x="93" y="66" textAnchor="middle" className="fill-accent-text font-mono" fontSize="8">85.60 mm</text>
    </svg>
  );
}

function PhotoArt() {
  return (
    <svg viewBox="0 0 200 120" className="h-full w-full" aria-hidden>
      <rect x="28" y="70" width="144" height="36" rx="3" className="fill-white stroke-border-strong" strokeWidth="1.5" />
      {[0, 1, 2, 3, 4].map((i) => (
        <rect key={i} x={34 + i * 30} y={74} width="7" height="7" fill="#111" />
      ))}
      <path d="M80 92 h40 l6 -6 h-12 v-4 h-28 z" className="fill-surface-3 stroke-fg" strokeWidth="1.2" />
      <rect x="78" y="10" width="44" height="44" rx="8" className="fill-surface stroke-fg" strokeWidth="1.5" />
      <circle cx="100" cy="32" r="9" className="fill-surface-2 stroke-fg" strokeWidth="1.5" />
      <circle cx="100" cy="32" r="3.5" className="fill-accent" />
      <path d="M100 56 L100 66" className="stroke-accent" strokeWidth="1.5" strokeDasharray="2 3" />
    </svg>
  );
}

function VerifiedArt() {
  return (
    <svg viewBox="0 0 200 120" className="h-full w-full" aria-hidden>
      <path d="M48 84 V44 h70 a16 16 0 0 1 0 32 H78 v8 z" className="fill-surface-2 stroke-fg" strokeWidth="1.5" />
      <circle cx="117" cy="60" r="6" className="fill-bg stroke-fg" strokeWidth="1.5" />
      <path d="M48 96 H134" className="stroke-muted" strokeWidth="1" />
      <path d="M48 92 v8 M134 92 v8" className="stroke-muted" strokeWidth="1" />
      <text x="91" y="108" textAnchor="middle" className="fill-muted font-mono" fontSize="8">length · mm</text>
      <rect x="138" y="20" width="44" height="18" rx="4" className="fill-ok-soft stroke-ok-border" strokeWidth="1" />
      <path d="M145 29 l3 3 l6 -6" className="stroke-ok" strokeWidth="1.8" fill="none" />
      <text x="168" y="32" textAnchor="middle" className="fill-ok" fontSize="7.5" fontWeight="600">OK</text>
    </svg>
  );
}

const STEPS = [
  {
    n: "01",
    title: "Your screen becomes the ruler",
    body: "Match a bank card on screen once. PartSmith then draws a marker mat at true size on your laptop or tablet — no printer, no caliper.",
    art: MatArt,
  },
  {
    n: "02",
    title: "Lay the part on it, take a photo",
    body: "Top view on the mat, optionally one from the side. Instant checks tell you to retake if markers are hidden, the photo is blurred or tilted.",
    art: PhotoArt,
  },
  {
    n: "03",
    title: "Get a part that is proven to match",
    body: "An agent writes parametric CAD; code renders it and compares it to your photo until it is inside tolerance. Then STL, 3MF and STEP.",
    art: VerifiedArt,
  },
];

export function HowItWorks({ className }: { className?: string }) {
  return (
    <ol className={cn("grid grid-cols-1 gap-4 md:grid-cols-3", className)}>
      {STEPS.map(({ n, title, body, art: Art }) => (
        <li key={n} className="flex flex-col overflow-hidden rounded-xl border border-border bg-surface">
          <div className="aspect-[5/3] border-b border-border bg-surface-2 bg-dots p-3">
            <Art />
          </div>
          <div className="space-y-1.5 p-5">
            <div className="font-mono text-[12px] text-accent-text">{n}</div>
            <h3 className="text-[15px] font-semibold tracking-tight">{title}</h3>
            <p className="text-[13px] leading-5 text-muted">{body}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}
