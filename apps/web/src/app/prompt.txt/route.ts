import { promptTxt } from "@/lib/agent-text";
import { apiOrigin } from "@/lib/api-origin";

export const dynamic = "force-dynamic";

/** Proxies the API's live `/api/v1/prompt.txt` (generated from the registry); falls back to the web copy when the API is down. */
export async function GET(req: Request): Promise<Response> {
  const origin = process.env.NEXT_PUBLIC_SITE_URL ?? new URL(req.url).origin;
  const base = apiOrigin();
  try {
    const res = await fetch(`${base}/api/v1/prompt.txt`, { cache: "no-store", signal: AbortSignal.timeout(3000), headers: { "X-Forwarded-Host": new URL(origin).host, "X-Forwarded-Proto": new URL(origin).protocol.replace(":", "") } });
    if (res.ok) {
      // The API builds absolute links from X-Forwarded-Host/-Proto, so they point at this web origin.
      const text = await res.text();
      return new Response(text, { headers: { "Content-Type": "text/plain; charset=utf-8", "X-PartSmith-Source": "api" } });
    }
  } catch {
    /* API offline: serve the built-in copy below */
  }
  return new Response(await promptTxt(origin), { headers: { "Content-Type": "text/plain; charset=utf-8", "X-PartSmith-Source": "web-fallback" } });
}
