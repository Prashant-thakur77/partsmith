"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { StatusDot } from "../ui/status-dot";
import { Tooltip } from "../ui/tooltip";

export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000, retry: false, staleTime: 10_000 });
}

export function ApiHealth() {
  const h = useHealth();
  const tone = h.isPending ? "idle" : h.data?.ok ? "ok" : "bad";
  const text = h.isPending ? "Checking API…" : h.data?.ok ? `API online · v${h.data.version}` : "API offline — run make dev";
  return (
    <Tooltip content={text}>
      <Link
        href="/status"
        className="inline-flex h-8 items-center gap-2 rounded-md px-2 text-[12px] text-muted hover:bg-surface-2 hover:text-fg"
        aria-label={text}
      >
        <StatusDot tone={tone} pulse={h.isPending} />
        <span className="hidden xl:inline">{h.isPending ? "API" : h.data?.ok ? "API online" : "API offline"}</span>
      </Link>
    </Tooltip>
  );
}
