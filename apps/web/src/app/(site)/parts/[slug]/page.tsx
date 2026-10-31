import type { Metadata } from "next";
import { HydrationBoundary, QueryClient, dehydrate } from "@tanstack/react-query";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { PartRecordSchema } from "@/lib/api-types";
import { Container } from "@/components/layout/page";
import { api } from "@/lib/api";
import { PartClient } from "./part-client";
import { PartDetails } from "./part-details";
import { apiOrigin } from "@/lib/api-origin";

/** The part, "missing" when the API answers 404 (a real 404 page), or null when the API could not be asked (the client retries). */
async function fetchPart(slug: string) {
  try {
    const base = apiOrigin();
    const res = await fetch(`${base}/api/v1/parts/${encodeURIComponent(slug)}`, { cache: "no-store", signal: AbortSignal.timeout(2500) });
    if (res.status === 404) return "missing" as const;
    if (!res.ok) return null;
    const parsed = PartRecordSchema.safeParse(await res.json());
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

async function apiHasRoute(path: string): Promise<boolean> {
  try {
    const base = apiOrigin();
    const r = await fetch(`${base}/api/v1/openapi.json`, { next: { revalidate: 3600 }, signal: AbortSignal.timeout(1500) });
    if (!r.ok) return false;
    const doc = (await r.json()) as { paths?: Record<string, unknown> };
    const norm = (p: string) => p.replace(/\{[^}]*\}/g, "{}");
    return Object.keys(doc.paths ?? {}).some((k) => norm(k) === norm(path));
  } catch {
    return false;
  }
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const found = await fetchPart(decodeURIComponent(slug));
  const part = found === "missing" ? null : found;
  if (!part) return { title: found === "missing" ? "Part not found" : slug, description: "A parametric replacement part in the PartSmith registry: typed knobs, verification record, STL, 3MF and STEP." };
  const err = part.verification?.verified ? part.verification.max_error_mm : null;
  const status = part.verification?.verified ? "" : part.status === "best_effort" ? " Best effort (not verified)." : "";
  const description = `${(part.summary || part.title).replace(/\.+$/, "")}. ${part.params.length} knobs${err != null ? `, verified at ${err.toFixed(2)} mm max error vs photo` : ""}. STL, 3MF, STEP and CadQuery source.${status}`;
  // Per-part share card (rendered by the API) when this backend serves one. The route list is read from the API's
  // OpenAPI document once an hour (cached), so the page does not wait on rendering a PNG.
  const card = `/api/v1/parts/${encodeURIComponent(part.slug)}/card.png`;
  const hasCard = await apiHasRoute("/api/v1/parts/{slug}/card.png");
  const images = hasCard ? [{ url: card, width: 1200, height: 630, alt: `${part.title} — PartSmith` }] : undefined;
  return {
    title: part.title,
    description,
    openGraph: { title: `${part.title} · PartSmith`, description, ...(images ? { images } : {}) },
    twitter: { card: "summary_large_image", ...(images ? { images: images.map((i) => i.url) } : {}) },
  };
}

export default async function PartPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const s = decodeURIComponent(slug);
  // Server-render the part (title, facts, thumbnail poster) so the first paint is the real page, not a skeleton.
  const qc = new QueryClient();
  const found = await fetchPart(s);
  if (found === "missing") notFound();
  const part = found;
  if (part) qc.setQueryData(["part", s], part);
  // Static sections (provenance, lineage, knob reference, matching) render here without client JS.
  const matching = part ? await api.matching(s).catch((e: unknown) => e) : null;
  return (
    <HydrationBoundary state={dehydrate(qc)}>
      <Suspense>
        <PartClient slug={s} withDetails={!part} />
      </Suspense>
      {part ? (
        <Container className="space-y-14 pt-6 pb-8">
          <PartDetails part={part} matching={matching} />
        </Container>
      ) : null}
    </HydrationBoundary>
  );
}
