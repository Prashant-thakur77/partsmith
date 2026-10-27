"use client";

import { useSyncExternalStore } from "react";

/** The site's origin in the browser (for copyable URLs); a placeholder host during SSR. */
export function useOrigin(): string {
  return useSyncExternalStore(
    () => () => {},
    () => window.location.origin,
    () => process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000",
  );
}
