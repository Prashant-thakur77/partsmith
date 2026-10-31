"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Minus, X } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { criteriaLine, criterionValue, type AdminPart } from "@/lib/api-admin";
import { timeAgo, titleCase } from "@/lib/format";
import { adminApi } from "./api";
import { ReasonForm } from "./bits";

type Show = "all" | "withdrawn" | "missing";

function PartRow({ p }: { p: AdminPart }) {
  const qc = useQueryClient();
  const [asking, setAsking] = React.useState(false);
  const action = p.withdrawn ? "republish" : "unpublish";
  const m = useMutation({
    mutationFn: (reason: string) => adminApi.moderate(p.slug, action, reason),
    onSuccess: () => {
      setAsking(false);
      void qc.invalidateQueries({ queryKey: ["admin"] });
    },
  });
  return (
    <li className="space-y-3 rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <Link href={`/parts/${encodeURIComponent(p.slug)}`} className="block break-words text-[14px] font-semibold text-fg hover:underline">
            {p.title}
          </Link>
          <p className="flex flex-wrap items-center gap-1.5 text-[12px] text-muted">
            <span className="break-all font-mono">{p.slug}</span>
            <Badge tone="neutral">{titleCase(p.family)}</Badge>
            <Badge tone="outline">{p.status.replace("_", " ")}</Badge>
            {p.reference ? <Badge tone="info">reference object</Badge> : null}
            {p.withdrawn ? <Badge tone="bad">withdrawn</Badge> : null}
          </p>
        </div>
        {!asking ? (
          <Button size="sm" variant="outline" onClick={() => setAsking(true)}>
            {p.withdrawn ? "Put back in search" : "Withdraw"}
          </Button>
        ) : null}
      </div>
      {p.withdrawn ? (
        <p className="text-[12.5px] text-muted">
          Withdrawn {timeAgo(p.withdrawn.at)} by {p.withdrawn.by}: “{p.withdrawn.reason}”
        </p>
      ) : null}
      <div>
        <p className="mb-1.5 text-[12px] font-medium text-muted tnum">{criteriaLine(p)}</p>
        <ul className="grid grid-cols-1 gap-1 sm:grid-cols-2" aria-label={`Publish checks for ${p.title}`}>
          {p.criteria.map((c) => (
            <li key={c.key} className="flex min-w-0 items-start gap-2 text-[12.5px]" title={`From ${c.source}`}>
              {c.ok === true ? (
                <Check className="mt-0.5 size-3.5 shrink-0 text-ok" aria-hidden />
              ) : c.ok === false ? (
                <X className="mt-0.5 size-3.5 shrink-0 text-bad" aria-hidden />
              ) : (
                <Minus className="mt-0.5 size-3.5 shrink-0 text-subtle" aria-hidden />
              )}
              <span className="min-w-0">
                <span className="sr-only">{c.ok === true ? "Met: " : c.ok === false ? "Not met: " : "Not checked: "}</span>
                <span className="text-fg">{c.label}</span> <span className="break-words text-muted tnum">· {criterionValue(c)}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>
      {asking ? (
        <ReasonForm
          label={p.withdrawn ? "Why does it go back in search?" : "Why take it out of search? It stays reachable by its link."}
          confirm={p.withdrawn ? "Put back" : "Withdraw"}
          busy={m.isPending}
          onSubmit={(r) => m.mutate(r)}
          onCancel={() => setAsking(false)}
        />
      ) : null}
      {m.isError ? <ErrorState error={m.error} compact what="the change" /> : null}
    </li>
  );
}

export function PartsTab() {
  const q = useQuery({ queryKey: ["admin", "parts"], queryFn: adminApi.parts, retry: false });
  const [show, setShow] = React.useState<Show>("all");
  if (q.isPending) return <Skeleton className="h-64" />;
  if (q.isError) return <ErrorState error={q.error} what="the parts list" onRetry={() => void q.refetch()} />;
  const items = q.data.items.filter((p) => (show === "withdrawn" ? !!p.withdrawn : show === "missing" ? p.met < p.checked : true));
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="max-w-2xl text-[13px] leading-5 text-muted">
          Each part with the checks code ran on it. Withdrawing takes a part out of search, the agent search and llms.txt; its link keeps working and says it was withdrawn.
        </p>
        <label className="space-y-1 text-[12px] text-muted">
          <span className="block">Show</span>
          <Select value={show} onChange={(e) => setShow(e.target.value as Show)}>
            <option value="all">All ({q.data.n})</option>
            <option value="missing">Missing a check</option>
            <option value="withdrawn">Withdrawn ({q.data.withdrawn})</option>
          </Select>
        </label>
      </div>
      {items.length ? (
        <ul className="space-y-3">{items.map((p) => <PartRow key={p.slug} p={p} />)}</ul>
      ) : (
        <EmptyState compact title="No parts match" />
      )}
      <p className="text-[11px] text-subtle">From {q.data.source}</p>
    </div>
  );
}
