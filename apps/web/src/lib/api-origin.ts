/**
 * Origin of the PartSmith API for server-side code (rewrites, SSR prefetch, the SSE pass-through, llms.txt).
 * `API_URL` first, then `NEXT_PUBLIC_API_URL` (the name the deploy guide uses on Vercel), else the local dev API.
 * The browser never calls the API directly: it uses same-origin `/api/v1/*`, which the web app proxies.
 */
export function apiOrigin(): string {
  return (process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
}
