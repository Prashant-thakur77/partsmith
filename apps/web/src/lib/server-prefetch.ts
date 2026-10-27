/**
 * Server-side prefetch of the site-wide health/status so the honesty banner is in the first paint (no layout shift).
 * Short timeout; on any failure the client fetches as before. Parsed with the same Zod schemas as the client.
 */
import "server-only";
import { QueryClient, dehydrate, type DehydratedState } from "@tanstack/react-query";
import type { z } from "zod/mini";
import { HealthSchema, StatusSchema } from "./api-types";

const base = () => `${(process.env.API_URL ?? "http://localhost:8000").replace(/\/$/, "")}/api/v1`;

async function get<S extends z.ZodMiniType>(path: string, schema: S): Promise<z.output<S> | undefined> {
  try {
    const res = await fetch(`${base()}${path}`, { next: { revalidate: 30 }, signal: AbortSignal.timeout(800) });
    if (!res.ok) return undefined;
    const parsed = schema.safeParse(await res.json());
    return parsed.success ? parsed.data : undefined;
  } catch {
    return undefined;
  }
}

export async function prefetchShell(): Promise<DehydratedState> {
  const qc = new QueryClient();
  const [health, status] = await Promise.all([get("/health", HealthSchema), get("/status", StatusSchema)]);
  if (health) qc.setQueryData(["health"], health);
  if (status) qc.setQueryData(["status"], status);
  return dehydrate(qc);
}
