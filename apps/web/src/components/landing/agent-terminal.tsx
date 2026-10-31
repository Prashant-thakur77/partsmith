"use client";

/**
 * A terminal that types an agent's MCP call, then the answer drops in as a part card. The search is real: it runs the
 * same registry search (`GET /parts?q=…&verified=true`) for the family of the newest verified part (or, with an empty
 * registry, the recorded run's part) and shows what came back — or the empty answer and the tool an agent calls next.
 */
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { api, artifactUrl } from "@/lib/api";
import { splitTitle } from "@/lib/format";
import { useInView, usePrefersReducedMotion } from "@/lib/motion";
import { PartCard } from "../registry/part-card";
import { Badge } from "../ui/badge";
import { useStoredRun } from "./use-figure-run";

export function AgentTerminal() {
  const { fig } = useStoredRun("figure");
  const reduced = usePrefersReducedMotion();
  const { ref, seen } = useInView<HTMLDivElement>({ threshold: 0.4 });
  // ask for something the registry may hold: the family of its newest verified part, else the recorded run's part
  const newest = useQuery({ queryKey: ["parts", "hero"], queryFn: () => api.parts({ verified: true, limit: 4, sort: "newest" }), retry: false });
  const fromRun = fig ? splitTitle(fig.title.replace(/\s*·\s*review round \d+\s*$/i, "")).title.toLowerCase().replace(/[^a-z0-9 ]+/g, " ").trim().split(/\s+/).slice(0, 2).join(" ") : "";
  const family = newest.data?.items[0]?.family.replace(/_/g, " ");
  const words = newest.isPending ? "" : (family ?? fromRun);
  const search = useQuery({ queryKey: ["parts", "agent-demo", words], queryFn: () => api.parts({ q: words, verified: true, limit: 1 }), enabled: !!words && seen, retry: false });
  const call = `tools/call search_parts {"q": "${words}", "verified": true}`;
  const [n, setN] = React.useState(0);
  React.useEffect(() => {
    if (!seen || !words) return;
    if (reduced) return setN(call.length);
    setN(0);
    const t = setInterval(() => setN((x) => (x >= call.length ? (clearInterval(t), x) : x + 2)), 28);
    return () => clearInterval(t);
  }, [seen, reduced, call.length, words]);
  const typed = n >= call.length;
  const hit = search.data?.items[0];
  // warm the answer card's picture while the call is still typing, so the card never drops in blank
  React.useEffect(() => {
    const src = artifactUrl(hit?.thumbnail_url);
    if (src) new Image().src = src;
  }, [hit?.thumbnail_url]);
  // the card's slot is held from the first paint while a verified answer is likely, so the tabs below never jump
  const likely = newest.isPending || ((newest.data?.items.length ?? 0) > 0 && !(search.isSuccess && !hit));
  return (
    <div ref={ref} className="space-y-3">
      <div className="overflow-hidden rounded-xl border border-ink/70 bg-[var(--term-bg)] text-[var(--term-fg)] shadow-md">
        <div className="flex items-center gap-1.5 border-b border-[var(--term-line)] px-3 py-2">
          {[0, 1, 2].map((i) => (
            <span key={i} className="size-2 rounded-full bg-[var(--term-dim)]" aria-hidden />
          ))}
          <span className="ml-2 font-mono text-[11px] text-[var(--term-dim)]">agent → partsmith (MCP)</span>
        </div>
        <pre className="min-h-[148px] overflow-x-auto px-4 py-3 font-mono text-[12px] leading-6 whitespace-pre-wrap">
          <span className="text-[var(--term-dim)]">$ </span>
          <span>{call.slice(0, n)}</span>
          {!typed ? <span aria-hidden className="ml-0.5 inline-block h-3.5 w-1.5 translate-y-0.5 bg-[var(--term-caret)] motion-safe:animate-[caret_900ms_steps(1)_infinite]" /> : null}
          {typed ? (
            <>
              {"\n"}
              <span className="text-[var(--term-dim)]">← </span>
              {search.isPending ? (
                <span className="text-[var(--term-dim)]">searching…</span>
              ) : search.isError ? (
                <span className="text-[var(--term-bad)]">the registry did not answer</span>
              ) : hit ? (
                <span className="text-[var(--term-ok)]">
                  {search.data!.total} verified {search.data!.total === 1 ? "part" : "parts"} · {hit.slug}
                </span>
              ) : (
                <>
                  <span className="text-[var(--term-warn)]">0 verified parts match</span>
                  {"\n"}
                  <span className="text-[var(--term-dim)]">$ </span>
                  <span>tools/call report_need {`{"query": "${words}"}`}</span>
                </>
              )}
            </>
          ) : null}
        </pre>
      </div>
      <div className={likely || (typed && hit) ? "min-h-[340px]" : undefined} data-testid="agent-answer-slot">
        {typed && hit ? (
          <div className="max-w-[280px] motion-safe:animate-[drop-in_420ms_var(--ease-stamp)_both]">
            <PartCard part={hit} eager />
          </div>
        ) : typed && search.isSuccess ? (
          <p className="flex flex-wrap items-center gap-2 text-[12.5px] text-muted motion-safe:animate-[drop-in_420ms_var(--ease-stamp)_both]">
            <Badge tone="outline">real search</Badge> The registry on this server has no verified match yet, so the agent reports the need instead of inventing a part.
          </p>
        ) : null}
      </div>
    </div>
  );
}
