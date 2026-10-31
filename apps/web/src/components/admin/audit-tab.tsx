"use client";

import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { changeText } from "@/lib/api-admin";
import { fmtDate } from "@/lib/format";
import { adminApi } from "./api";

export function AuditTab() {
  const [action, setAction] = React.useState("");
  const q = useQuery({ queryKey: ["admin", "audit", action], queryFn: () => adminApi.audit({ limit: 200, action: action || undefined }), retry: false });
  const actions = useQuery({ queryKey: ["admin", "audit", ""], queryFn: () => adminApi.audit({ limit: 200 }), retry: false, enabled: !!action });
  const names = (action ? actions.data?.actions : q.data?.actions) ?? [];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="max-w-2xl text-[13px] leading-5 text-muted">Every admin change, newest first: who, what, before and after. The log is only ever added to.</p>
        <label className="space-y-1 text-[12px] text-muted">
          <span className="block">Action</span>
          <Select value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">All</option>
            {names.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </Select>
        </label>
      </div>
      {q.isPending ? (
        <Skeleton className="h-48" />
      ) : q.isError ? (
        <ErrorState error={q.error} what="the audit log" onRetry={() => void q.refetch()} />
      ) : q.data.items.length ? (
        <>
          <p className="text-[12px] text-muted tnum">
            Showing {q.data.items.length} of {q.data.total}
          </p>
          <ol className="divide-y divide-border rounded-lg border border-border bg-surface">
            {q.data.items.map((e, i) => (
              <li key={e.id || `${e.at}-${i}`} className="space-y-1 p-3 text-[13px]">
                <p className="flex flex-wrap items-center gap-1.5">
                  <Badge tone="accent">{e.action}</Badge>
                  <span className="break-all font-mono text-[12px] text-fg">{e.target}</span>
                  <span className="text-[12px] text-subtle">
                    {fmtDate(e.at)} · {e.actor}
                  </span>
                </p>
                {e.note ? <p className="break-words text-muted">“{e.note}”</p> : null}
                <p className="break-words text-[12px] text-muted tnum">
                  {changeText(e.before)} → {changeText(e.after)}
                </p>
              </li>
            ))}
          </ol>
        </>
      ) : (
        <EmptyState compact title="Nothing logged yet">Admin changes show up here as they happen.</EmptyState>
      )}
      {q.data ? <p className="text-[11px] text-subtle">From {q.data.source}</p> : null}
    </div>
  );
}
