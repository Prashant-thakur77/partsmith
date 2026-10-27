"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, Inbox, Send } from "lucide-react";
import * as React from "react";
import { Container, PageHeader, Section } from "@/components/layout/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input, Label } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { toast } from "@/components/ui/toast";
import { api, artifactUrl } from "@/lib/api";
import { useCapabilities } from "@/lib/capabilities";
import type { Need } from "@/lib/api-types";
import { timeAgo } from "@/lib/format";

const STATUS: Record<Need["status"], { label: string; tone: "neutral" | "accent" | "ok" }> = {
  open: { label: "open", tone: "neutral" },
  in_progress: { label: "being built", tone: "accent" },
  fulfilled: { label: "in the registry", tone: "ok" },
};

/** Needs board: what people want that the registry does not have. One vote per client (the API decides what counts). */
export function RequestsClient() {
  const qc = useQueryClient();
  const needs = useQuery({ queryKey: ["needs"], queryFn: api.needs });
  const [text, setText] = React.useState("");
  const [photo, setPhoto] = React.useState<File | null>(null);
  const [voted, setVoted] = React.useState<Set<string>>(new Set());
  const caps = useCapabilities();
  const onRecorded = (n: Need) => {
    void qc.invalidateQueries({ queryKey: ["needs"] });
    setVoted((s) => new Set(s).add(n.id));
    if (n.counted === false) toast("Already counted", { description: "One vote per person for each request." });
  };
  const onFail = (e: unknown) => toast("Could not record that", { description: e instanceof Error ? e.message : String(e), tone: "bad" });
  const post = useMutation({ mutationFn: (q: string) => api.createNeed(q, photo), onSuccess: onRecorded, onError: onFail });
  const vote = useMutation({
    mutationFn: (n: Need) => (caps.has("post", "/needs/{id}/vote") ? api.voteNeed(n.id) : api.createNeed(n.query)),
    onSuccess: onRecorded,
    onError: onFail,
  });
  const list = [...(needs.data ?? [])].sort((a, b) => b.votes - a.votes);
  return (
    <>
      <PageHeader
        eyebrow="Requests"
        title="Parts people are asking for"
        description="When search comes up empty, people (and agents) record what they needed. The most-wanted parts get built next."
      />
      <Container className="space-y-10 py-8">
        <form
          className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-5 sm:flex-row sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim())
              post.mutate(text.trim(), {
                onSuccess: () => {
                  setText("");
                  setPhoto(null);
                },
              });
          }}
        >
          <div className="min-w-0 flex-1 space-y-1.5">
            <Label htmlFor="need">What part do you need?</Label>
            <Input id="need" value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Usha cooler wheel, 32 mm, 8 mm axle" />
          </div>
          <div className="space-y-1.5 sm:w-56">
            <Label htmlFor="need-photo">Photo (optional)</Label>
            <input
              id="need-photo"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              onChange={(e) => setPhoto(e.target.files?.[0] ?? null)}
              className="block w-full text-[12px] text-muted file:mr-2 file:h-8 file:rounded-md file:border file:border-border file:bg-surface-2 file:px-2 file:text-[12px] file:text-fg"
            />
          </div>
          <Button type="submit" variant="primary" disabled={!text.trim() || post.isPending}>
            {post.isPending ? <Spinner className="text-accent-fg" label="Sending" /> : <Send aria-hidden />} Request it
          </Button>
        </form>
        <Section title="Most wanted" description="Votes come from repeat requests and the vote buttons here; the server counts one per person.">
          {needs.isPending ? (
            <div className="space-y-2">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-14" />
              ))}
            </div>
          ) : needs.isError ? (
            <ErrorState error={needs.error} what="requests" onRetry={() => void needs.refetch()} />
          ) : list.length === 0 ? (
            <EmptyState icon={Inbox} title="No requests yet">
              Be the first: describe the part above, with any size you know.
            </EmptyState>
          ) : (
            <ol className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface">
              {list.map((n) => (
                <li key={n.id} className="flex items-center gap-3 px-4 py-3">
                  <button
                    type="button"
                    onClick={() => vote.mutate(n)}
                    disabled={voted.has(n.id) || vote.isPending || n.status === "fulfilled"}
                    aria-label={`${n.votes} votes. Vote for: ${n.query}`}
                    aria-pressed={voted.has(n.id)}
                    className="flex w-12 shrink-0 flex-col items-center rounded-md border border-border py-1 text-muted hover:border-border-strong hover:text-fg disabled:opacity-60"
                  >
                    <ArrowUp className="size-3.5" aria-hidden />
                    <span className="font-mono text-[13px] font-medium text-fg tnum">{n.votes}</span>
                  </button>
                  {n.photo_url ? (
                    // eslint-disable-next-line @next/next/no-img-element -- API blob
                    <img src={artifactUrl(n.photo_url)} alt="" loading="lazy" className="size-10 shrink-0 rounded-md border border-border object-cover" />
                  ) : null}
                  <div className="min-w-0 flex-1">
                    <p className="text-[14px] font-medium text-fg">{n.query}</p>
                    {n.created_at ? <p className="text-[12px] text-subtle">{timeAgo(n.created_at)}</p> : null}
                  </div>
                  <Badge tone={STATUS[n.status].tone}>{STATUS[n.status].label}</Badge>
                </li>
              ))}
            </ol>
          )}
        </Section>
      </Container>
    </>
  );
}
