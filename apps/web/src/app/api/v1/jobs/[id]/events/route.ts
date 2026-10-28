/**
 * SSE pass-through for `/api/v1/jobs/{id}/events`. The generic rewrite proxy lets `next start` gzip the response, which
 * buffers the stream until the job ends; this handler streams it unbuffered (`no-transform`) so the workspace is live.
 */
import { apiOrigin } from "@/lib/api-origin";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
// Serverless hosts cut long responses; the client resumes with Last-Event-ID / from_seq, so nothing is lost.
export const maxDuration = 300;

export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await params;
  const base = apiOrigin();
  const url = new URL(req.url);
  const target = `${base}/api/v1/jobs/${encodeURIComponent(id)}/events${url.search}`;
  const headers: Record<string, string> = { Accept: "text/event-stream" };
  const lastId = req.headers.get("last-event-id");
  if (lastId) headers["Last-Event-ID"] = lastId;
  let upstream: Response;
  try {
    upstream = await fetch(target, { headers, signal: req.signal, cache: "no-store" });
  } catch {
    return Response.json({ error: { code: "api_unreachable", message: "The PartSmith API is not reachable." } }, { status: 502 });
  }
  if (!upstream.ok || !upstream.body) {
    return new Response(await upstream.text(), { status: upstream.status, headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json" } });
  }
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
