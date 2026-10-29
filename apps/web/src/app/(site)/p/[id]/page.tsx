import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Container } from "@/components/layout/page";
import { apiOrigin } from "@/lib/api-origin";
import { ApiErrorBodySchema, PassportSchema, type Passport } from "@/lib/api-types";
import { normalizePassportId } from "@/lib/passport";
import { PassportClient, PassportNotFound } from "./passport-client";

type Lookup = { passport: Passport } | { missing: { message: string; closest: string[] } } | { offline: true };

async function lookup(id: string): Promise<Lookup> {
  try {
    const res = await fetch(`${apiOrigin()}/api/v1/passport/${encodeURIComponent(id)}`, { cache: "no-store", signal: AbortSignal.timeout(4000) });
    const body: unknown = await res.json().catch(() => null);
    if (res.ok) {
      const parsed = PassportSchema.safeParse(body);
      return parsed.success ? { passport: parsed.data } : { offline: true };
    }
    const err = ApiErrorBodySchema.safeParse(body);
    if (res.status === 404 && err.success) return { missing: { message: err.data.error.message, closest: err.data.error.closest_matches ?? [] } };
    return { offline: true };
  } catch {
    return { offline: true };
  }
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  const pid = normalizePassportId(decodeURIComponent(id)) ?? decodeURIComponent(id);
  return {
    title: `Passport ${pid}`,
    description: "A PartSmith repair passport: reprint this part from its verified model, with your printer's learned clearance.",
    robots: { index: false },
  };
}

export default async function PassportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const raw = decodeURIComponent(id);
  const res = await lookup(normalizePassportId(raw) ?? raw);
  // A job that was never published has no part page yet: its passport opens the job itself.
  if ("passport" in res && res.passport.kind === "job") redirect(res.passport.page_url);
  return (
    <Container className="py-8 sm:py-10">
      {"passport" in res ? (
        <PassportClient passport={res.passport} />
      ) : (
        <PassportNotFound id={raw} message={"missing" in res ? res.missing.message : null} closest={"missing" in res ? res.missing.closest : []} />
      )}
    </Container>
  );
}
