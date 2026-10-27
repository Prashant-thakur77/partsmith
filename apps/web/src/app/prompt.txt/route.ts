import { promptTxt } from "@/lib/agent-text";

export async function GET(req: Request): Promise<Response> {
  const origin = process.env.NEXT_PUBLIC_SITE_URL ?? new URL(req.url).origin;
  return new Response(promptTxt(origin), { headers: { "Content-Type": "text/plain; charset=utf-8" } });
}
