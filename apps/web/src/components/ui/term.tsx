"use client";

import type * as React from "react";
import { GLOSSARY, splitTerms, type GlossaryKey } from "@/lib/glossary";
import { cn } from "@/lib/utils";
import { Tooltip } from "./tooltip";

/** A word with its plain meaning one hover, focus or tap away. */
export function Term({ k, children, className }: { k: GlossaryKey; children?: React.ReactNode; className?: string }) {
  const entry = GLOSSARY[k];
  return (
    <Tooltip
      tap
      className="whitespace-normal"
      content={
        <>
          <span className="font-semibold">{entry.title}.</span> {entry.text}
        </>
      }
    >
      <button type="button" className={cn("cursor-help text-left underline decoration-dotted decoration-1 underline-offset-[3px]", className)}>
        {children ?? entry.title}
      </button>
    </Tooltip>
  );
}

/** A sentence with each glossary word in it explained once. */
export function TermText({ text }: { text: string }) {
  return (
    <>
      {splitTerms(text).map((piece, i) =>
        typeof piece === "string" ? (
          piece
        ) : (
          <Term key={i} k={piece.key}>
            {piece.word}
          </Term>
        ),
      )}
    </>
  );
}
