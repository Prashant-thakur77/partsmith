"use client";

import { useQuery } from "@tanstack/react-query";
import { Info } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Says so beside a button that would ask a model for something this server can't really ask: with no model keys, the
 * model steps run on recorded or stand-in answers. Nothing shows on a server with live models, or before the status is known.
 */
export function NoKeysNote({ what, className }: { what: string; className?: string }) {
  const status = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 60_000, retry: false });
  const mode = status.data?.mode;
  if (mode !== "replay" && mode !== "mock") return null;
  return (
    <p role="note" data-testid="no-keys" className={cn("flex items-start gap-2 rounded-md border border-warn-border bg-warn-soft px-3 py-2 text-[12.5px] leading-5 text-fg", className)}>
      <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <span>
        This server has no model keys. {what} To see the real thing, open{" "}
        <Link href="/judges" className="font-medium underline underline-offset-2">
          a recorded live run
        </Link>
        .
      </span>
    </p>
  );
}
