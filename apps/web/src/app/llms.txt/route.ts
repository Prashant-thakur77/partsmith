import { llmsTxt } from "@/lib/agent-text";

export const dynamic = "force-dynamic";

/** Proxies the API's live `/api/v1/llms.txt` (generated from the registry); falls back to the web copy when the API is down. */
export async function GET(req: Request): Promise<Response> {
  const origin = process.env.NEXT_PUBLIC_SITE_URL ?? new URL(req.url).origin;
  const base = (process.env.API_URL ?? "http://localhost:8000").replace(/\/$/, "");
  try {
    const res = await fetch(`${base}/api/v1/llms.txt`, { cache: "no-store", signal: AbortSignal.timeout(3000), headers: { "X-Forwarded-Host": new URL(origin).host } });
    if (res.ok) {
      // The API writes its own host into links; the web origin proxies the same paths, so point readers there.
      const text = (await res.text()).split(base).join(origin);
      return new Response(text, { headers: { "Content-Type": "text/plain; charset=utf-8", "X-PartSmith-Source": "api" } });
    }
  } catch {
    /* API offline: serve the built-in copy below */
  }
  return new Response(await llmsTxt(origin), { headers: { "Content-Type": "text/plain; charset=utf-8", "X-PartSmith-Source": "web-fallback" } });
}
