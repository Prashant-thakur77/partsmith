import { llmsTxt } from "@/lib/agent-text";

export const revalidate = 300;

export async function GET(req: Request): Promise<Response> {
  const origin = process.env.NEXT_PUBLIC_SITE_URL ?? new URL(req.url).origin;
  return new Response(await llmsTxt(origin), { headers: { "Content-Type": "text/plain; charset=utf-8" } });
}
