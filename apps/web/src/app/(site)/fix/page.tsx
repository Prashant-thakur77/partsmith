import { FlaskConical } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { Container } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { FixClient } from "./fix-client";

export const metadata: Metadata = {
  title: "Fix a part",
  description: "Calibrate your screen, photograph the broken part on the mat, and start a verified fix job.",
};

/** Static header renders on the server; the three interactive steps are the client island. */
export default function FixPage() {
  return (
    <>
      <Container className="pt-8 sm:pt-10">
        <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="max-w-2xl space-y-2">
            <div className="text-[12px] font-medium uppercase tracking-[0.08em] text-accent-text">Fix a broken part</div>
            <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.025em] sm:text-[34px]">From photo to verified part</h1>
            <p className="text-[15px] leading-6 text-muted">
              Three steps, about two minutes. You can watch every measurement and every model iteration live once the job starts.
            </p>
          </div>
          <Button asChild variant="outline">
            <Link href="/jobs/demo">
              <FlaskConical aria-hidden /> Try a synthetic sample
            </Link>
          </Button>
        </div>
      </Container>
      <FixClient />
    </>
  );
}
