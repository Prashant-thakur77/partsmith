import type { MetadataRoute } from "next";

const PAGES = ["", "/fix", "/how", "/proof", "/compare", "/gallery", "/results", "/models", "/judges", "/parts", "/playground", "/describe", "/agents", "/lessons", "/review", "/requests", "/shop", "/jobs"];

/** The public pages, for search engines and agents. */
export default function sitemap(): MetadataRoute.Sitemap {
  const site = (process.env.NEXT_PUBLIC_SITE_URL ?? "").replace(/\/$/, "");
  return PAGES.map((path) => ({ url: `${site}${path || "/"}` }));
}
