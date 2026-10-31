"use client";

import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { ADMIN_API } from "@/lib/api-admin";
import { useCapabilities } from "@/lib/capabilities";
import { timeAgo } from "@/lib/format";
import { adminApi } from "./api";
import { Bars, Panel } from "./bits";

const STATUS = { open: "open", in_progress: "in progress", fulfilled: "done" } as const;

function Missed() {
  const q = useQuery({ queryKey: ["admin", "demand"], queryFn: adminApi.demand, retry: false });
  if (q.isPending) return <Skeleton className="h-32" />;
  if (q.isError) return <ErrorState error={q.error} what="missed searches" onRetry={() => void q.refetch()} />;
  const rows = q.data.missed_searches;
  return (
    <Panel title="Searches that found nothing good" source="GET /demand on this server">
      {rows.length ? (
        <ul className="divide-y divide-border text-[13px]">
          {rows.map((m) => (
            <li key={m.q} className="flex flex-wrap items-baseline justify-between gap-x-3 py-1.5">
              <span className="min-w-0 break-words text-fg">{m.q}</span>
              <span className="text-muted tnum">
                {m.count}× · best match {m.best_coverage == null ? "none" : `${Math.round(m.best_coverage * 100)}%`}
                {m.last_at && Number.isFinite(Date.parse(m.last_at)) ? ` · ${timeAgo(Date.parse(m.last_at) / 1000)}` : ""}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-[13px] text-muted">No missed searches recorded.</p>
      )}
    </Panel>
  );
}

export function DemandTab() {
  const caps = useCapabilities();
  const needs = useQuery({ queryKey: ["needs"], queryFn: api.needs, enabled: caps.has("get", ADMIN_API.needs), retry: false });
  const hasDemand = caps.has("get", ADMIN_API.demand);
  return (
    <div className="space-y-4">
      <p className="max-w-2xl text-[13px] leading-5 text-muted">What people asked for and could not find. Requests come from the requests page; votes are one per visitor.</p>
      <Panel title="Requested parts, most votes first" source="GET /needs (registry requests)">
        {needs.isPending ? (
          <Skeleton className="h-32" />
        ) : needs.isError ? (
          <ErrorState error={needs.error} what="requests" onRetry={() => void needs.refetch()} />
        ) : needs.data.length ? (
          <Bars
            label="Requests by votes"
            rows={needs.data.slice(0, 20).map((n) => ({
              key: n.id,
              label: (
                <>
                  {n.query} <Badge tone={n.status === "fulfilled" ? "ok" : n.status === "in_progress" ? "info" : "neutral"}>{STATUS[n.status]}</Badge>
                </>
              ),
              value: n.votes,
              text: `${n.votes} vote${n.votes === 1 ? "" : "s"}`,
            }))}
          />
        ) : (
          <EmptyState compact title="No requests yet" />
        )}
      </Panel>
      {!caps.ready ? null : hasDemand ? (
        <Missed />
      ) : (
        <p className="text-[12px] text-subtle">This server does not record missed searches yet, so none are shown.</p>
      )}
    </div>
  );
}
