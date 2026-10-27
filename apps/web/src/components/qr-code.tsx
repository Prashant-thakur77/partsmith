"use client";

/** QR code drawn locally as SVG (no external service), always dark-on-white with a quiet zone so phones read it. */
import * as React from "react";
import { encode } from "uqr";
import { cn } from "@/lib/utils";

export function QrCode({ value, size = 168, className, label }: { value: string; size?: number; className?: string; label: string }) {
  const path = React.useMemo(() => {
    const { data } = encode(value, { ecc: "M", border: 0 });
    let d = "";
    data.forEach((row, y) => row.forEach((on, x) => on && (d += `M${x} ${y}h1v1h-1z`)));
    return { d, n: data.length };
  }, [value]);
  const q = 4; // quiet zone in modules
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`${-q} ${-q} ${path.n + 2 * q} ${path.n + 2 * q}`}
      width={size}
      height={size}
      shapeRendering="crispEdges"
      className={cn("rounded-md bg-white", className)}
    >
      <rect x={-q} y={-q} width={path.n + 2 * q} height={path.n + 2 * q} fill="#fff" />
      <path d={path.d} fill="#111" />
    </svg>
  );
}
