"use client";

/**
 * Draws a calibration mat at true 1:1 on a calibrated screen: an SVG whose viewBox is in mat millimetres and whose CSS size
 * is width_mm × px_per_mm. Marker cells come straight from the layout's `bits` (7×7 incl. border, 1 = white) and are drawn as
 * crisp rects. The stage stays plain white so the part's silhouette separates cleanly. `children` render in the mat frame (mm).
 */
import * as React from "react";
import type { MatLayout } from "@/lib/api-types";
import { STAGE_COLOURS, type StageTone } from "@/lib/stage";

function markerPath(m: MatLayout["markers"][number]): string {
  const n = m.bits.length;
  const cell = m.size_mm / n;
  let d = "";
  m.bits.forEach((row, r) => {
    row.forEach((bit, c) => {
      if (bit === 0) {
        const x = m.x_mm + c * cell;
        const y = m.y_mm + r * cell;
        d += `M${x.toFixed(4)} ${y.toFixed(4)}h${cell.toFixed(4)}v${cell.toFixed(4)}h${(-cell).toFixed(4)}z`;
      }
    });
  });
  return d;
}

export function ScreenMat({
  layout,
  pxPerMm,
  rotated = false,
  children,
  className,
  title,
  stage = "light",
}: {
  layout: MatLayout;
  pxPerMm: number;
  rotated?: boolean;
  children?: React.ReactNode;
  className?: string;
  title?: string;
  /** Stage rectangle fill; the marker ring and its quiet zone stay white. */
  stage?: StageTone;
}) {
  const path = React.useMemo(() => layout.markers.map(markerPath).join(""), [layout]);
  const w = layout.width_mm * pxPerMm;
  const h = layout.height_mm * pxPerMm;
  const svg = (
    <svg
      role="img"
      aria-label={title ?? `${layout.title}, drawn at 1:1 scale`}
      width={w}
      height={h}
      viewBox={`0 0 ${layout.width_mm} ${layout.height_mm}`}
      shapeRendering="crispEdges"
      className="block bg-white"
      style={{ width: w, height: h }}
    >
      <rect x={0} y={0} width={layout.width_mm} height={layout.height_mm} fill="#ffffff" />
      {stage !== "light" ? (
        <rect x={layout.stage.x_mm} y={layout.stage.y_mm} width={layout.stage.w_mm} height={layout.stage.h_mm} fill={STAGE_COLOURS[stage]} />
      ) : null}
      <path d={path} fill="#000000" />
      <g shapeRendering="geometricPrecision">{children}</g>
    </svg>
  );
  if (!rotated) return <div className={className}>{svg}</div>;
  // Portrait screens: rotate the whole mat 90° so the long side runs along the long screen edge.
  return (
    <div className={className} style={{ width: h, height: w, position: "relative" }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: w, height: h, transformOrigin: "0 0", transform: `translateX(${h}px) rotate(90deg)` }}>
        {svg}
      </div>
    </div>
  );
}
