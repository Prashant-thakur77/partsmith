"use client";

import { Heart, X } from "lucide-react";
import * as React from "react";
import { useT } from "@/lib/i18n";

const VOTE_URL = process.env.NEXT_PUBLIC_VOTE_URL ?? "";
export const VOTE_ENABLED = VOTE_URL !== "";

/** Subtle "vote for us" note after a part verifies. Hidden when NEXT_PUBLIC_VOTE_URL is unset or once dismissed. */
export function VoteBanner() {
  const { t } = useT();
  const [hidden, setHidden] = React.useState(false);
  if (!VOTE_URL || hidden) return null;
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-surface px-4 py-2.5 text-[13px]">
      <a href={VOTE_URL} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-2 font-medium text-fg hover:text-accent-text">
        <Heart className="size-4 text-accent" aria-hidden /> {t("ws.vote")}
      </a>
      <button type="button" onClick={() => setHidden(true)} aria-label="Dismiss" className="rounded p-1 text-subtle hover:bg-surface-2 hover:text-fg">
        <X className="size-3.5" aria-hidden />
      </button>
    </div>
  );
}
