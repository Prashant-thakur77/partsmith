import type { Page } from "@playwright/test";

/** Known backend race (see the integration report): GET /api/v1/jobs/{id} can answer 500 while the job is writing its
 * state file. The client retries it, so it is tolerated here — and only that. */
export const KNOWN_TRANSIENT = (method: string, url: string) => method === "GET" && /\/api\/v1\/jobs\/j_[^/?]+$/.test(new URL(url).pathname);

/** Collect page errors, console errors and 5xx responses (by URL), minus the documented transient. */
export function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => m.type() === "error" && !/Failed to load resource/.test(m.text()) && errors.push(m.text()));
  page.on("response", (r) => {
    if (r.status() >= 500 && !KNOWN_TRANSIENT(r.request().method(), r.url())) errors.push(`${r.status()} ${r.request().method()} ${r.url()}`);
    if (r.status() === 404 && !/\/blobs\//.test(r.url()) && /\/api\/v1\//.test(r.url())) errors.push(`404 ${r.url()}`);
  });
  return errors;
}
