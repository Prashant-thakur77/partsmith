import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { apiOrigin } from "@/lib/api-origin";
import { WorkspaceClient } from "./workspace-client";

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  return { title: `Job ${id}`, robots: { index: false } };
}

/** True only when the API answers 404 for this job; an unreachable API leaves it to the client (which says so). */
async function jobMissing(id: string): Promise<boolean> {
  try {
    const res = await fetch(`${apiOrigin()}/api/v1/jobs/${encodeURIComponent(id)}/presets`, { cache: "no-store", signal: AbortSignal.timeout(2500) });
    return res.status === 404 && ((await res.json().catch(() => null)) as { error?: { code?: string } } | null)?.error?.code === "job_not_found";
  } catch {
    return false;
  }
}

export default async function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const jobId = decodeURIComponent(id);
  if (await jobMissing(jobId)) notFound();
  return <WorkspaceClient id={jobId} />;
}
