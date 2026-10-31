import { Eye, ScanLine } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * The screen fit check, offered on the job page itself (the header button is easy to miss): lay the part on its own
 * outline drawn at true size on this screen and photograph it; code measures the gap. "See an example" opens a
 * labelled example drawn from this job's outline, so the check can be seen before calibrating a screen.
 */
export function FitCheckCard({ jobId, className }: { jobId: string; className?: string }) {
  const base = `/jobs/${encodeURIComponent(jobId)}/fit`;
  return (
    <section aria-labelledby="fit-check-card" className={cn("space-y-2.5 rounded-lg border border-border bg-surface p-4", className)} data-testid="fit-check-card">
      <h2 id="fit-check-card" className="flex items-center gap-2 text-[13px] font-semibold">
        <ScanLine className="size-4 text-muted" aria-hidden /> Check the fit on your screen
      </h2>
      <p className="text-[13px] leading-5 text-muted">
        Lay the real or printed part on this model&apos;s outline, drawn at true size on your screen, and take a photo. Code measures the gap. Needs a calibrated
        screen (30 seconds with a bank card).
      </p>
      <div className="flex flex-wrap gap-2">
        <Button asChild size="sm" variant="outline">
          <Link href={base}>
            <ScanLine aria-hidden /> Open the fit check
          </Link>
        </Button>
        <Button asChild size="sm" variant="ghost">
          <Link href={`${base}?example=1`}>
            <Eye aria-hidden /> See an example
          </Link>
        </Button>
      </div>
    </section>
  );
}
