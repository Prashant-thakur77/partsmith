"use client";

import * as React from "react";
import { useReveal } from "@/lib/motion";

/** A block that fades 8 px up once it scrolls into view (used for section headers across the site). */
export function Reveal({ className, children }: { className?: string; children: React.ReactNode }) {
  const reveal = useReveal<HTMLDivElement>();
  return (
    <div className={className} {...reveal}>
      {children}
    </div>
  );
}
