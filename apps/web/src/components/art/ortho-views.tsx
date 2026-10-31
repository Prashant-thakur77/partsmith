/**
 * Art B — a part shown the way a drawing set shows it: top, front and right-side views in third-angle projection, with
 * projection lines, the third-angle symbol and a title block. A picture only: it carries no measurements.
 */
import { cn } from "@/lib/utils";

const INK = "var(--ink)";
const THIN = { stroke: INK, strokeWidth: 0.6, strokeOpacity: 0.45, strokeDasharray: "4 3" } as const;

export function OrthoViews({ className, title = "Third-angle drawing of a hinge leaf: top, front and side views" }: { className?: string; title?: string }) {
  const holes = [104, 168, 232, 296];
  return (
    <svg viewBox="0 0 640 420" className={cn("h-auto w-full", className)} role="img" aria-label={title}>
      <rect x="4" y="4" width="632" height="412" rx="10" fill="var(--screen)" stroke={INK} strokeWidth="1.25" />
      <rect x="16" y="16" width="608" height="388" fill="none" stroke={INK} strokeWidth="0.6" strokeOpacity="0.5" />

      {/* projection lines */}
      <g {...THIN}>
        {[60, 92, 156, 212, 276, 340].map((x) => (
          <line key={x} x1={x} x2={x} y1={176} y2={232} />
        ))}
        <line x1={346} x2={440} y1={250} y2={250} />
        <line x1={346} x2={440} y1={262} y2={262} />
        <line x1={346} x2={440} y1={238} y2={238} />
      </g>

      {/* top view */}
      <g>
        <text x="60" y="44" fontSize="10" letterSpacing="0.14em" fill="var(--fg-muted)" className="font-mono">TOP</text>
        <path d="M60 78 H340 V158 A10 10 0 0 1 330 168 H70 A10 10 0 0 1 60 158 Z" fill="var(--stamp-fill)" stroke={INK} strokeWidth="1.4" />
        <rect x="92" y="56" width="64" height="22" rx="2" fill="var(--screen)" stroke={INK} strokeWidth="1.4" />
        <rect x="212" y="56" width="64" height="22" rx="2" fill="var(--screen)" stroke={INK} strokeWidth="1.4" />
        <line x1="52" x2="348" y1="67" y2="67" stroke={INK} strokeWidth="0.6" strokeDasharray="10 3 2 3" />
        {holes.map((x) => (
          <g key={x}>
            <circle cx={x} cy={126} r={11} fill="none" stroke={INK} strokeWidth="0.8" strokeOpacity="0.5" />
            <circle cx={x} cy={126} r={6} fill="var(--screen)" stroke={INK} strokeWidth="1.3" />
          </g>
        ))}
      </g>

      {/* front view */}
      <g>
        <text x="60" y="226" fontSize="10" letterSpacing="0.14em" fill="var(--fg-muted)" className="font-mono">FRONT</text>
        <rect x="60" y="250" width="280" height="12" fill="var(--stamp-fill)" stroke={INK} strokeWidth="1.4" />
        <rect x="92" y="238" width="64" height="24" rx="2" fill="var(--screen)" stroke={INK} strokeWidth="1.4" />
        <rect x="212" y="238" width="64" height="24" rx="2" fill="var(--screen)" stroke={INK} strokeWidth="1.4" />
        {holes.map((x) => (
          <g key={x} stroke={INK} strokeWidth="0.7" strokeDasharray="3 2" strokeOpacity="0.7">
            <line x1={x - 6} x2={x - 6} y1={250} y2={262} />
            <line x1={x + 6} x2={x + 6} y1={250} y2={262} />
          </g>
        ))}
      </g>

      {/* right side view */}
      <g>
        <text x="440" y="226" fontSize="10" letterSpacing="0.14em" fill="var(--fg-muted)" className="font-mono">SIDE</text>
        <path d="M440 262 V250 H508 A12 12 0 1 1 520 262 Z" fill="var(--stamp-fill)" stroke={INK} strokeWidth="1.4" />
        <circle cx="520" cy="250" r="5" fill="var(--screen)" stroke={INK} strokeWidth="1.2" />
        <path d="M512 250 H528 M520 242 V258" stroke={INK} strokeWidth="0.5" strokeOpacity="0.5" />
      </g>

      {/* third-angle projection symbol */}
      <g transform="translate(450 70)" stroke={INK} strokeWidth="1.1" fill="none">
        <path d="M0 10 L36 0 V40 L0 30 Z" />
        <line x1="-6" x2="96" y1="20" y2="20" strokeDasharray="8 2 2 2" strokeWidth="0.6" />
        <circle cx="72" cy="20" r="20" />
        <circle cx="72" cy="20" r="10" />
      </g>
      <text x="450" y="132" fontSize="9.5" letterSpacing="0.12em" fill="var(--fg-muted)" className="font-mono">THIRD-ANGLE PROJECTION</text>

      {/* title block */}
      <g className="font-mono" fontSize="9" fill="var(--fg-muted)">
        <rect x="380" y="306" width="232" height="86" fill="var(--screen)" stroke={INK} strokeWidth="1" />
        <line x1="380" x2="612" y1="336" y2="336" stroke={INK} strokeWidth="0.6" />
        <line x1="380" x2="612" y1="364" y2="364" stroke={INK} strokeWidth="0.6" />
        <line x1="496" x2="496" y1="336" y2="392" stroke={INK} strokeWidth="0.6" />
        <text x="388" y="318" letterSpacing="0.12em">PART</text>
        <text x="388" y="331" fontSize="11.5" fill="var(--fg)">Hinge leaf · illustration</text>
        <text x="388" y="346" letterSpacing="0.12em">SCALE</text>
        <text x="388" y="359" fontSize="11" fill="var(--fg)">1:1 on the mat</text>
        <text x="504" y="346" letterSpacing="0.12em">UNITS</text>
        <text x="504" y="359" fontSize="11" fill="var(--fg)">millimetres</text>
        <text x="388" y="374" letterSpacing="0.12em">DRAWN BY</text>
        <text x="388" y="387" fontSize="11" fill="var(--fg)">the agent</text>
        <text x="504" y="374" letterSpacing="0.12em">CHECKED BY</text>
        <text x="504" y="387" fontSize="11" fill="var(--stamp)">code</text>
      </g>
    </svg>
  );
}
