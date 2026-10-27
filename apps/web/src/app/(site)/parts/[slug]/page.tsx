import type { Metadata } from "next";
import { Suspense } from "react";
import { PartRecordSchema } from "@/lib/api-types";
import { PartClient } from "./part-client";

async function fetchPart(slug: string) {
  try {
    const base = (process.env.API_URL ?? "http://localhost:8000").replace(/\/$/, "");
    const res = await fetch(`${base}/api/v1/parts/${encodeURIComponent(slug)}`, { next: { revalidate: 60 }, signal: AbortSignal.timeout(1500) });
    if (!res.ok) return null;
    const parsed = PartRecordSchema.safeParse(await res.json());
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }): Promise<Metadata> {
  const { slug } = await params;
  const part = await fetchPart(decodeURIComponent(slug));
  if (!part) return { title: slug };
  const err = part.verification?.verified ? part.verification.max_error_mm : null;
  const description = `${part.summary || part.title}. ${part.params.length} knobs${err != null ? `, verified at ${err.toFixed(2)} mm max error vs photo` : ""}. STL, 3MF, STEP and CadQuery source.`;
  return { title: part.title, description, openGraph: { title: `${part.title} · PartSmith`, description } };
}

export default async function PartPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return (
    <Suspense>
      <PartClient slug={decodeURIComponent(slug)} />
    </Suspense>
  );
}
