"use client";

import { useInfiniteQuery, useMutation, useQuery } from "@tanstack/react-query";
import { Boxes, Camera, Megaphone, Search, SearchX, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { Container, PageHeader } from "@/components/layout/page";
import { PartCard, PartCardSkeleton } from "@/components/registry/part-card";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input, Select } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { toast } from "@/components/ui/toast";
import { Switch } from "@/components/ui/toggle";
import { api, type PartsQuery } from "@/lib/api";
import { extrasApi } from "@/lib/api-extras";
import { fmtInt } from "@/lib/format";
import { useDebounced } from "@/lib/hooks";
import { matchBanner, type MatchBanner } from "@/lib/search-match";
import { cn } from "@/lib/utils";

const SORTS: { v: NonNullable<PartsQuery["sort"]>; label: string }[] = [
  { v: "relevance", label: "Best match" },
  { v: "newest", label: "Newest" },
  { v: "error", label: "Lowest error" },
  { v: "title", label: "Name" },
];

export function PartsClient() {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const [q, setQ] = React.useState(sp.get("q") ?? "");
  const family = sp.get("family") ?? "";
  const verified = sp.get("verified") === "true";
  const sort = (sp.get("sort") as PartsQuery["sort"]) ?? undefined;
  const dq = useDebounced(q, 250);

  const setParam = React.useCallback(
    (patch: Record<string, string | null>) => {
      const next = new URLSearchParams(sp.toString());
      for (const [k, v] of Object.entries(patch)) {
        if (v) next.set(k, v);
        else next.delete(k);
      }
      router.replace(`${pathname}${next.toString() ? `?${next}` : ""}`, { scroll: false });
    },
    [router, pathname, sp],
  );
  React.useEffect(() => {
    if ((sp.get("q") ?? "") !== dq) setParam({ q: dq || null });
  }, [dq, sp, setParam]);

  const families = useQuery({ queryKey: ["families"], queryFn: api.families });
  const counts = families.data?.length
    ? families.data.reduce((acc, f) => ({ count: acc.count + f.count, verified: acc.verified + f.verified }), { count: 0, verified: 0 })
    : null;
  const list = useInfiniteQuery({
    queryKey: ["parts", { q: dq, family, verified, sort }],
    queryFn: ({ pageParam }) => extrasApi.parts({ q: dq || undefined, family: family || undefined, verified, sort, cursor: pageParam, limit: 24 }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const items = list.data?.pages.flatMap((p) => p.items) ?? [];
  const total = list.data?.pages[0]?.total;
  const first = list.data?.pages[0];
  const banner = first ? matchBanner(first.match, first.coverage, first.hint, dq) : null;

  const need = useMutation({
    mutationFn: (query: string) => api.createNeed(query),
    onSuccess: (n) => toast("Request recorded", { description: `“${n.query}” · ${n.votes} vote${n.votes === 1 ? "" : "s"}`, tone: "ok" }),
    onError: () => toast("Could not record the request", { tone: "bad" }),
  });

  return (
    <>
      <PageHeader
        eyebrow="Registry"
        title="Parametric parts"
        description={`${counts ? `${fmtInt(counts.verified)} of ${fmtInt(counts.count)} verified by code against their photos; the rest are best effort. ` : ""}Every part is a CadQuery program with typed knobs, a verification record and provenance. Drag the knobs, download STL, 3MF or STEP.`}
      />
      <Container className="space-y-6 py-8">
        <div className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-subtle" aria-hidden />
              <Input
                type="search"
                aria-label="Search parts"
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search: M3 standoff, battery cover 45 mm, cupboard latch…"
                className="h-10 pl-9"
              />
            </div>
            <div className="flex items-center gap-4">
              <Switch checked={verified} onCheckedChange={(v) => setParam({ verified: v ? "true" : null })} label="Verified only" />
              <Select aria-label="Sort" value={sort ?? ""} onChange={(e) => setParam({ sort: e.target.value || null })} className="h-10">
                <option value="">Sort: default</option>
                {SORTS.map((s) => (
                  <option key={s.v} value={s.v}>
                    {s.label}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          <div className="no-scrollbar -mx-4 flex gap-1.5 overflow-x-auto px-4 sm:mx-0 sm:flex-wrap sm:px-0" role="group" aria-label="Families">
            <Chip active={!family} onClick={() => setParam({ family: null })}>
              All
            </Chip>
            {/* a family with no parts yet has nothing to filter to (kept only while it is the active filter) */}
            {families.data?.filter((f) => f.count > 0 || family === f.family).map((f) => (
              <Chip key={f.family} active={family === f.family} onClick={() => setParam({ family: family === f.family ? null : f.family })}>
                {f.title}
                <span className="font-mono text-[11px] tnum">{f.verified}/{f.count}</span>
              </Chip>
            ))}
          </div>
        </div>

        <div className="flex items-center justify-between text-[13px] text-muted" aria-live="polite">
          <span>
            {list.isPending ? "Searching…" : total !== undefined ? `${fmtInt(total)} part${total === 1 ? "" : "s"}` : ""}
            {family ? <> in <span className="text-fg">{families.data?.find((f) => f.family === family)?.title ?? family}</span></> : null}
          </span>
          {q || family || verified ? (
            <button
              type="button"
              onClick={() => {
                setQ("");
                router.replace(pathname, { scroll: false });
              }}
              className="inline-flex items-center gap-1 text-[12px] hover:text-fg"
            >
              <X className="size-3.5" aria-hidden /> Clear filters
            </button>
          ) : null}
        </div>

        {list.isError ? (
          <ErrorState error={list.error} what="parts" onRetry={() => void list.refetch()} />
        ) : list.isPending ? (
          <div className="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 lg:grid-cols-4">
            {Array.from({ length: 8 }, (_, i) => (
              <PartCardSkeleton key={i} />
            ))}
          </div>
        ) : items.length === 0 && !dq && !family && !verified ? (
          <EmptyState
            icon={Boxes}
            title="No parts published yet"
            action={
              <>
                <Button asChild variant="primary" size="sm">
                  <Link href="/fix">Fix a part</Link>
                </Button>
                <Button asChild variant="outline" size="sm">
                  <Link href="/jobs/demo">Try a sample</Link>
                </Button>
              </>
            }
          >
            Every part here passed the photo check first. Fix a broken part to add the first one, or watch a sample run.
          </EmptyState>
        ) : items.length === 0 ? (
          <EmptyState
            icon={Search}
            title={dq ? `No verified part matches “${dq}”` : "No parts match these filters"}
            action={
              dq ? (
                <Button variant="outline" size="sm" onClick={() => need.mutate(dq)} disabled={need.isPending || need.isSuccess}>
                  {need.isPending ? <Spinner label="Sending" /> : <Megaphone aria-hidden />}
                  {need.isSuccess ? "Requested" : "Request this part"}
                </Button>
              ) : null
            }
          >
            PartSmith never substitutes an unrelated part. Ask for it and it goes on the build list —{" "}
            {dq ? (
              <>
                <Link href={`/describe?q=${encodeURIComponent(dq)}`} className="text-accent-text underline underline-offset-2">
                  describe it
                </Link>{" "}
                or{" "}
                <Link href="/fix" className="text-accent-text underline underline-offset-2">
                  fix it from a photo
                </Link>
                .
              </>
            ) : (
              "or fix your own and publish it."
            )}
          </EmptyState>
        ) : (
          <>
            {banner ? (
              <NoMatchBanner
                banner={banner}
                query={dq}
                onRequest={() => need.mutate(dq)}
                requesting={need.isPending}
                requested={need.isSuccess}
              />
            ) : null}
            <h2 className="sr-only">Results</h2>
            <div className="grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 lg:grid-cols-4">
              {items.map((p) => (
                <PartCard key={p.slug} part={p} />
              ))}
            </div>
            {list.hasNextPage ? (
              <div className="flex justify-center pt-2">
                <Button variant="outline" onClick={() => void list.fetchNextPage()} disabled={list.isFetchingNextPage}>
                  {list.isFetchingNextPage ? <Spinner label="Loading more" /> : null} Load more
                </Button>
              </div>
            ) : null}
          </>
        )}
      </Container>
    </>
  );
}

/** Shown above the results when the API says the best part matches only part of the query (or none of it). */
function NoMatchBanner({ banner, query, onRequest, requesting, requested }: { banner: MatchBanner; query: string; onRequest: () => void; requesting: boolean; requested: boolean }) {
  return (
    <div
      role="status"
      data-testid="search-match-banner"
      className={cn("space-y-2.5 rounded-lg border p-3 text-[13px]", banner.tone === "warn" ? "border-warn-border bg-warn-soft" : "border-border bg-surface-2")}
    >
      <div className="flex items-start gap-2">
        <SearchX className={cn("mt-0.5 size-4 shrink-0", banner.tone === "warn" ? "text-warn" : "text-muted")} aria-hidden />
        <div className="space-y-0.5">
          <p className="font-medium text-fg">
            {banner.title}
            {banner.coveragePct !== null ? <span className="ml-1.5 font-mono text-[11.5px] font-normal text-muted tnum">best part matches {banner.coveragePct} % of your words and sizes</span> : null}
          </p>
          {banner.hint ? <p className="text-muted">{banner.hint}</p> : null}
        </div>
      </div>
      <div className="flex flex-wrap gap-2 pl-6">
        <Button asChild variant="outline" size="sm">
          <Link href={`/describe?q=${encodeURIComponent(query)}`}>
            <Sparkles aria-hidden /> Describe it
          </Link>
        </Button>
        <Button asChild variant="outline" size="sm">
          <Link href="/fix">
            <Camera aria-hidden /> Fix from a photo
          </Link>
        </Button>
        <Button variant="ghost" size="sm" onClick={onRequest} disabled={requesting || requested}>
          {requesting ? <Spinner label="Sending" /> : <Megaphone aria-hidden />}
          {requested ? "Requested" : "Request it"}
        </Button>
      </div>
    </div>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-[13px] transition-colors",
        active ? "border-fg bg-fg text-bg" : "border-border bg-surface text-muted hover:border-border-strong hover:text-fg",
      )}
    >
      {children}
    </button>
  );
}
