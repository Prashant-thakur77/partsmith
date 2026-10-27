"use client";

import { AlertTriangle, RotateCw } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";
import { Button } from "@/components/ui/button";

export default function SiteError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <div className="flex min-h-[60vh] items-center justify-center px-4 py-24">
      <div className="max-w-md space-y-5 text-center">
        <div className="mx-auto flex size-11 items-center justify-center rounded-full border border-bad-border bg-bad-soft text-bad">
          <AlertTriangle className="size-5" aria-hidden />
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">Something broke on this page</h1>
        <p className="text-[14px] leading-6 text-muted">
          The error was logged{error.digest ? <> (ref <span className="font-mono">{error.digest}</span>)</> : null}. Try again, or head back home.
        </p>
        <div className="flex justify-center gap-2">
          <Button variant="primary" onClick={reset}>
            <RotateCw aria-hidden /> Try again
          </Button>
          <Button asChild variant="outline">
            <Link href="/">Home</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
