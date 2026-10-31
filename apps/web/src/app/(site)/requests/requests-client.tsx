"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUp, ImagePlus, Inbox, Send, X } from "lucide-react";
import * as React from "react";
import { Container, PageHeader, Section } from "@/components/layout/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ExamplePreview } from "@/components/ui/example-preview";
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
  const fileRef = React.useRef<HTMLInputElement>(null);
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
                  if (fileRef.current) fileRef.current.value = "";
                },
              });
          }}
        >
          <div className="min-w-0 flex-1 space-y-1.5">
            <Label htmlFor="need">What part do you need?</Label>
            <Input id="need" value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Usha cooler wheel, 32 mm, 8 mm axle" />
          </div>
          <div className="space-y-1.5 sm:w-56">
            <span id="need-photo-label" className="block text-[13px] font-medium text-fg">
              Photo (optional)
            </span>
            <div className="flex items-center gap-1.5">
              <input
                ref={fileRef}
                id="need-photo"
                type="file"
                accept="image/jpeg,image/png,image/webp"
                aria-labelledby="need-photo-label"
                onChange={(e) => setPhoto(e.target.files?.[0] ?? null)}
                className="peer sr-only"
              />
              <label
                htmlFor="need-photo"
                className="inline-flex h-9 min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-md border border-border-strong bg-surface px-3 text-[13px] text-fg shadow-sm hover:border-subtle peer-focus-visible:ring-2 peer-focus-visible:ring-ring/30"
              >
                <ImagePlus className="size-4 shrink-0 text-muted" aria-hidden />
                <span className="truncate">{photo ? photo.name : "Add a photo"}</span>
              </label>
              {photo ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label="Remove the photo"
                  onClick={() => {
                    setPhoto(null);
                    if (fileRef.current) fileRef.current.value = "";
                  }}
                >
                  <X aria-hidden />
                </Button>
              ) : null}
            </div>
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
            <div className="space-y-4">
              <EmptyState
                compact
                icon={Inbox}
                title="No requests yet"
                action={
                  <Button type="button" variant="primary" size="sm" onClick={() => document.getElementById("need")?.focus()}>
                    <Send aria-hidden /> Request a part
                  </Button>
                }
              >
                For anyone who searched the registry and came up empty, people and agents alike. Describe the part above with any size you know; the most-wanted
                parts get built next.
              </EmptyState>
              <ExamplePreview title="What a request looks like" kind="illustration · not a real request">
                <div className="flex items-center gap-3 rounded-lg border border-border bg-surface px-4 py-3">
                  <span className="flex w-12 shrink-0 flex-col items-center rounded-md border border-dashed border-border py-1 text-muted" aria-hidden>
                    <ArrowUp className="size-3.5" />
                    <span className="font-mono text-[11px]">vote</span>
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-[14px] font-medium text-fg">Cooler wheel, 32 mm across, 8 mm axle</p>
                    <p className="text-[12px] text-subtle">Others who need the same part vote it up; the server counts one vote per person.</p>
                  </div>
                  <Badge tone="neutral">open</Badge>
                </div>
              </ExamplePreview>
            </div>
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
