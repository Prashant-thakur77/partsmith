"use client";

import { AlertTriangle, ArrowLeft, PlugZap, RotateCw } from "lucide-react";
import Link from "next/link";
import { ApiError, ApiSchemaError, isOffline } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button } from "./button";

/** Renders an API failure honestly: offline backend, HTTP error with its code, or a contract mismatch. Never fake data. */
export function ErrorState({
  error,
  onRetry,
  className,
  compact = false,
  what = "this",
  back,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
  compact?: boolean;
  what?: string;
  /** Where to go when the thing does not exist (a 404): shown instead of "Try again", which would only fail again. */
  back?: { href: string; label: string };
}) {
  const missing = error instanceof ApiError && error.status === 404;
  const offline = isOffline(error);
  const Icon = offline ? PlugZap : AlertTriangle;
  let title = `Could not load ${what}`;
  let body: React.ReactNode = error instanceof Error ? error.message : String(error);
  if (offline) {
    title = "The PartSmith API is offline";
    body = (
      <>
        The server is not answering right now; try again in a minute. Nothing here is shown from cached or invented data.
      </>
    );
  } else if (error instanceof ApiError) {
    title = error.status === 404 ? `Not found` : `Request failed (${error.status})`;
    body = (
      <>
        <span className="font-mono text-[12px]">{error.code}</span> · {error.message}
        {error.closestMatches.length ? <> Did you mean: {error.closestMatches.join(", ")}?</> : null}
      </>
    );
  } else if (error instanceof ApiSchemaError) {
    title = "The API answered with an unexpected shape";
  }
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center rounded-lg border text-center",
        offline ? "border-dashed border-border-strong bg-surface" : "border-bad-border bg-bad-soft/40",
        compact ? "gap-2 px-4 py-5" : "gap-3 px-6 py-12",
        className,
      )}
    >
      <div className={cn("flex size-10 items-center justify-center rounded-full border", offline ? "border-border bg-surface-2 text-muted" : "border-bad-border bg-surface text-bad")}>
        <Icon className="size-[18px]" aria-hidden />
      </div>
      <div className="max-w-md space-y-1">
        <p className="text-sm font-medium text-fg">{title}</p>
        <p className="text-[13px] leading-5 text-muted">{body}</p>
      </div>
      {missing && back ? (
        <Button asChild size="sm" variant="outline">
          <Link href={back.href}>
            <ArrowLeft aria-hidden /> {back.label}
          </Link>
        </Button>
      ) : onRetry ? (
        <Button size="sm" variant="outline" onClick={onRetry}>
          <RotateCw aria-hidden /> Try again
        </Button>
      ) : null}
    </div>
  );
}
