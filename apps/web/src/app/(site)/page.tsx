import { ArrowRight, Calculator, Eye, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { AgentsStrip } from "@/components/landing/agents-strip";
import { BenchStrip } from "@/components/landing/bench-strip";
import { BenchView } from "@/components/landing/bench-view";
import { RegistryView } from "@/components/landing/registry-view";
import { StatsView } from "@/components/landing/stats-view";
import { HowItWorks } from "@/components/landing/how-it-works";
import { HeroDemo } from "@/components/landing/hero-demo";
import { RegistryPreview } from "@/components/landing/registry-preview";
import { ReplayLoopLazy } from "@/components/landing/replay-loop-lazy";
import { StatsStrip } from "@/components/landing/stats-strip";
import { Container, Section } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

/**
 * Below-the-fold sections render on the server (no client JS); if the API could not be reached at render time the same
 * sections render as client components that fetch in the browser.
 */
export default async function HomePage() {
  const [stats, bench, preview] = await Promise.allSettled([api.stats(), api.bench(), api.parts({ limit: 8, sort: "newest" })]);
  return (
    <>
      <div className="relative overflow-hidden border-b border-border">
        <div className="pointer-events-none absolute inset-0 bg-dots [mask-image:radial-gradient(ellipse_at_30%_20%,black,transparent_70%)]" aria-hidden />
        <Container className="relative grid items-center gap-10 py-12 sm:py-16 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:gap-12 lg:py-20">
          <div className="space-y-6">
            <div className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-[12px] text-muted shadow-sm">
              <span className="size-1.5 rounded-full bg-accent" aria-hidden />
              Photo → millimetres → verified CAD
            </div>
            <h1 className="text-[36px] leading-[1.05] font-semibold tracking-[-0.035em] text-fg sm:text-[48px] lg:text-[52px]">
              A broken plastic part in. A <span className="text-accent-text">proven</span> replacement out.
            </h1>
            <p className="max-w-xl text-[16px] leading-7 text-muted sm:text-[17px]">
              Lay the part on your screen and take a photo. PartSmith measures it in millimetres, writes parametric CAD, and checks the
              model against your photo until it matches. Code decides when it is good enough — not the AI.
            </p>
            <div className="flex flex-wrap gap-2.5">
              <Button asChild variant="primary" size="lg">
                <Link href="/fix">
                  Fix a broken part <ArrowRight aria-hidden />
                </Link>
              </Button>
              <Button asChild variant="outline" size="lg">
                <Link href="/parts">Browse verified parts</Link>
              </Button>
            </div>
            <ul className="flex flex-col gap-2 pt-2 text-[13px] text-muted sm:flex-row sm:flex-wrap sm:gap-x-5">
              <li className="inline-flex items-center gap-1.5">
                <Calculator className="size-4 text-subtle" aria-hidden /> No printer, caliper or special paper
              </li>
              <li className="inline-flex items-center gap-1.5">
                <ShieldCheck className="size-4 text-subtle" aria-hidden /> Verified by code, every number traceable
              </li>
              <li className="inline-flex items-center gap-1.5">
                <Eye className="size-4 text-subtle" aria-hidden /> Mocks and samples always labelled
              </li>
            </ul>
          </div>
          <div className="min-w-0">
            <div className="mb-2 flex items-center justify-between text-[12px] text-muted">
              <span className="shrink-0 font-medium text-fg">Try the knobs</span>
              <span className="hidden sm:inline">Real registry parts · re-baked on the server as you drag</span>
            </div>
            <HeroDemo />
          </div>
        </Container>
      </div>

      <Container className="space-y-20 py-14 sm:py-16">
        {stats.status === "fulfilled" ? <StatsView stats={stats.value} state="ok" /> : <StatsStrip />}

        <Section id="how" title="How it works" description="Three steps. The middle one is a phone photo.">
          <HowItWorks />
        </Section>

        <Section id="replay" title="Watch one run" description="A stored run played back from its own event log: the photo, the mask, every iteration's error, and the verifier's verdict.">
          <ReplayLoopLazy />
        </Section>

        <Section
          id="proof"
          title="The model proposes. Code decides."
          description="The agent writes CadQuery; a deterministic verifier renders it and compares silhouettes and features with your photo. Only the verifier can award the Verified badge. Accuracy is reported against three ground-truth sources that are never merged."
          actions={
            <Button asChild variant="ghost" size="sm">
              <Link href="/results">
                Full bench <ArrowRight aria-hidden />
              </Link>
            </Button>
          }
        >
          {bench.status === "fulfilled" ? <BenchView report={bench.value} state="ok" /> : <BenchStrip />}
        </Section>

        <Section
          id="registry"
          title="An open registry of verified parts"
          description="Each part is a program with typed knobs, a verification record and provenance — not a frozen mesh."
          actions={
            <Button asChild variant="ghost" size="sm">
              <Link href="/parts">
                All parts <ArrowRight aria-hidden />
              </Link>
            </Button>
          }
        >
          {preview.status === "fulfilled" ? <RegistryView items={preview.value.items} /> : <RegistryPreview />}
        </Section>

        <AgentsStrip />
      </Container>
    </>
  );
}
