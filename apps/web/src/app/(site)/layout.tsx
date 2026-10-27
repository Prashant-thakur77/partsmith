import { HydrationBoundary } from "@tanstack/react-query";
import { SiteFooter } from "@/components/shell/site-footer";
import { SiteHeader } from "@/components/shell/site-header";
import { prefetchShell } from "@/lib/server-prefetch";

export default async function SiteLayout({ children }: { children: React.ReactNode }) {
  const state = await prefetchShell();
  return (
    <HydrationBoundary state={state}>
      <div className="flex min-h-dvh flex-col">
        <a
          href="#main"
          className="sr-only z-50 rounded-md bg-surface px-3 py-2 text-sm shadow-md focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
        >
          Skip to content
        </a>
        <SiteHeader />
        {/* min height keeps the footer below the fold while client data loads (no layout shift) */}
        <main id="main" className="min-h-[calc(100dvh-3.5rem)] flex-1">
          {children}
        </main>
        <SiteFooter />
      </div>
    </HydrationBoundary>
  );
}
