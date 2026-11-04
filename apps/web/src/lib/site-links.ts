/**
 * The site's outside links: a copy of the same keys in the repo's docs/links.json (the web image builds from apps/web alone).
 * test/site-links.test.mjs fails when the two drift apart.
 */
export const LINKS = {
  repo: "https://github.com/Prashant-thakur77/partsmith",
  video: "https://youtu.be/bdMTeAaa7dY",
} as const;

export const REPO_URL = process.env.NEXT_PUBLIC_REPO_URL || LINKS.repo;
export const FILM_URL: string = LINKS.video;
export const DECK_PATH = "/deck/index.html";

/** The video id of a YouTube link (youtu.be/ID or youtube.com/watch?v=ID), or null when it is not one. */
export function youtubeId(url: string): string | null {
  try {
    const u = new URL(url);
    if (u.hostname === "youtu.be") return u.pathname.slice(1) || null;
    if (u.hostname.endsWith("youtube.com")) return u.searchParams.get("v");
  } catch {
    return null;
  }
  return null;
}

/** The player address on YouTube's privacy-enhanced host; it is only ever requested after a press on play. */
export function filmEmbedUrl(url: string): string | null {
  const id = youtubeId(url);
  return id ? `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}?autoplay=1&rel=0` : null;
}
