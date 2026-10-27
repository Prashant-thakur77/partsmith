import Link from "next/link";
import { SiteFooter } from "@/components/shell/site-footer";
import { SiteHeader } from "@/components/shell/site-header";
import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="flex min-h-dvh flex-col">
      <SiteHeader />
      <main id="main" className="flex flex-1 items-center justify-center px-4 py-24">
        <div className="max-w-md space-y-5 text-center">
          <div className="font-mono text-[13px] text-accent-text">404 · 0.00 mm of page found</div>
          <h1 className="text-3xl font-semibold tracking-tight">This page doesn&apos;t exist</h1>
          <p className="text-[15px] leading-6 text-muted">The link may be old, or the part was renamed. Search the registry or start a fix.</p>
          <div className="flex justify-center gap-2">
            <Button asChild variant="primary">
              <Link href="/parts">Search parts</Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/">Home</Link>
            </Button>
          </div>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
