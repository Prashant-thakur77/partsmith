import type { Metadata } from "next";
import { api } from "@/lib/api";
import { EmbedViewer } from "./embed-viewer";

export const metadata: Metadata = { title: "Embedded part", robots: { index: false } };

/** Minimal embeddable viewer for `<iframe src="/embed/parts/{slug}">`: model, title, verdict, link back. */
export default async function EmbedPartPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const s = decodeURIComponent(slug);
  const part = await api.part(s).catch(() => null);
  return <EmbedViewer slug={s} part={part} />;
}
