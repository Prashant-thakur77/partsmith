"use client";

import * as React from "react";
import { splitNumeric } from "@/lib/count-up";
import { useCountUp, useInView } from "@/lib/motion";
import { cn } from "@/lib/utils";

/**
 * A formatted real value ("0.10 mm", "17/17") that counts up once when it scrolls into view (~700 ms). Screen readers
 * and the server HTML get the final text; with reduced motion it never animates. `unitClassName` styles a trailing
 * unit (" mm") separately from the number.
 */
export function CountUp({ text, className, unitClassName, ms = 700, start }: { text: string; className?: string; unitClassName?: string; ms?: number; start?: boolean }) {
  const { ref, seen } = useInView<HTMLSpanElement>({ threshold: 0.6 });
  const shown = useCountUp(text, start ?? seen, ms) ?? text;
  const unit = unitClassName ? splitNumeric(text)?.suffix : undefined;
  const split = unit && unit.startsWith(" ") && shown.endsWith(unit);
  return (
    <span ref={ref} className={cn("tnum", className)}>
      <span aria-hidden>
        {split ? (
          <>
            {shown.slice(0, shown.length - unit.length)}
            <span className={unitClassName}>{unit}</span>
          </>
        ) : (
          shown
        )}
      </span>
      <span className="sr-only">{text}</span>
    </span>
  );
}
