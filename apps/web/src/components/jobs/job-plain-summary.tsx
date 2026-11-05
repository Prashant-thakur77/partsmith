"use client";

import { AlertTriangle, ArrowRight, CheckCircle2, Hourglass, XCircle } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Term, TermText } from "@/components/ui/term";
import type { JobPlain, PlainAction, PlainTone } from "@/lib/plain-summary";
import { cn } from "@/lib/utils";

const TONE: Record<PlainTone, { icon: typeof CheckCircle2; text: string; border: string }> = {
  ok: { icon: CheckCircle2, text: "text-ok", border: "border-ok-border" },
  warn: { icon: AlertTriangle, text: "text-warn", border: "border-warn-border" },
  bad: { icon: XCircle, text: "text-bad", border: "border-bad-border" },
  busy: { icon: Hourglass, text: "text-subtle", border: "border-border" },
};

function Heading({ children }: { children: React.ReactNode }) {
  return <h2 className="text-[11.5px] font-medium tracking-wide text-subtle uppercase">{children}</h2>;
}

function ActionLink({ action, jobId }: { action: PlainAction; jobId: string }) {
  if (action === "fit") {
    return (
      <Button asChild variant="outline" size="sm">
        <Link href={`/jobs/${encodeURIComponent(jobId)}/fit`}>
          Check the fit <ArrowRight aria-hidden />
        </Link>
      </Button>
    );
  }
  if (action === "review") {
    return (
      <Button asChild variant="outline" size="sm">
        <Link href={`/review?job=${encodeURIComponent(jobId)}`}>
          Open it in review <ArrowRight aria-hidden />
        </Link>
      </Button>
    );
  }
  if (action === "fix") {
    return (
      <Button asChild variant="outline" size="sm">
        <Link href="/fix">
          Start a new fix <ArrowRight aria-hidden />
        </Link>
      </Button>
    );
  }
  return (
    <Button asChild variant="ghost" size="sm">
      <a href="#model-viewer">See the model</a>
    </Button>
  );
}

/** What happened, why, and what to do next, above everything else on the job page. */
export function JobPlainSummary({ plain, jobId }: { plain: JobPlain; jobId: string }) {
  const tone = TONE[plain.tone];
  return (
    <section
      aria-label="In plain words"
      data-testid="job-plain"
      className={cn("grid grid-cols-1 gap-x-8 gap-y-4 rounded-lg border bg-surface p-4 md:grid-cols-[minmax(0,1.05fr)_minmax(0,1.3fr)_minmax(0,1fr)]", tone.border)}
    >
      <div className="min-w-0 space-y-1.5">
        <Heading>What happened</Heading>
        <p className="flex items-start gap-2 text-[15px] leading-[1.35] font-medium text-fg">
          <tone.icon className={cn("mt-0.5 size-4 shrink-0", tone.text)} aria-hidden />
          <span>{plain.happened}</span>
        </p>
        {plain.label ? <p className="text-[12px] leading-[1.4] text-subtle">{plain.label}</p> : null}
      </div>
      <div className="min-w-0 space-y-1.5">
        <Heading>Why</Heading>
        {plain.why.length ? (
          <ul className="space-y-1 text-[13px] leading-[1.45] text-muted">
            {plain.why.map((line) => (
              <li key={line}>
                <TermText text={line} />
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[13px] text-muted">The job left no reason.</p>
        )}
      </div>
      <div className="min-w-0 space-y-2">
        <Heading>What to do next</Heading>
        <p className="text-[13px] leading-[1.45] text-fg">{plain.next}</p>
        {plain.actions.length ? (
          <div className="flex flex-wrap items-center gap-2">
            {plain.actions.map((action) => (
              <ActionLink key={action} action={action} jobId={jobId} />
            ))}
          </div>
        ) : null}
      </div>
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border pt-3 text-[12px] text-muted md:col-span-3">
        <span className="text-subtle">Words on this page:</span>
        <Term k="hausdorff" />
        <Term k="iou" />
        <Term k="parametric" />
        <Term k="verifier" />
        <Term k="mat" />
      </p>
    </section>
  );
}
