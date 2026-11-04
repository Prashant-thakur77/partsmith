import { ArrowRight, FlaskConical, PenLine, PlayCircle, SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { AgentsStrip } from "@/components/landing/agents-strip";
import { BuyOrPrintStrip } from "@/components/landing/buy-or-print-strip";
import { ClosingCta } from "@/components/landing/closing-cta";
import { FilmEmbed } from "@/components/landing/film-embed";
import { FiveSheets } from "@/components/landing/five-sheets";
import { FixItself } from "@/components/landing/fix-itself";
import { HeroFigure } from "@/components/landing/hero-figure";
import { HeroModel } from "@/components/landing/hero-model";
import { HeroTicker } from "@/components/landing/hero-ticker";
import { JudgePath } from "@/components/landing/judge-path";
import { LieStrip } from "@/components/landing/lie-strip";
import { ProgramSection } from "@/components/landing/program-section";
import { ProofStrip } from "@/components/landing/proof-strip";
import { Sheet } from "@/components/landing/sheet";
import { SignOff } from "@/components/landing/sign-off";
import { Container } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

/** The landing page is a drawing set: the hero is sheet 1, the closing call to action the last. */
const SHEETS = ["hero", "proof", "how", "loop", "lie", "program", "buy", "review", "agents", "cta"] as const;
const OF = SHEETS.length;
const n = (id: (typeof SHEETS)[number]) => SHEETS.indexOf(id) + 1;

/**
 * Numbers render from the API on the server when it answers (stats, bench); everything else reads stored runs in the
 * browser. Each section says where its numbers come from, and stored runs are labelled "recorded run".
 */
export default async function HomePage() {
  const [stats, bench] = await Promise.allSettled([api.stats(), api.bench()]);
  const statsV = stats.status === "fulfilled" ? stats.value : null;
  const benchV = bench.status === "fulfilled" ? bench.value : null;
  return (
    <>
      <div className="relative overflow-hidden border-b border-border">
        <div className="pointer-events-none absolute inset-0 bg-paper [mask-image:radial-gradient(ellipse_80%_70%_at_60%_40%,black,transparent_85%)]" aria-hidden />
        <Container className="relative py-6 sm:py-8">
          <div className="page-in mb-6 sm:mb-8">
            <HeroTicker stats={statsV} bench={benchV} />
          </div>
          <div className="grid items-center gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.06fr)] lg:gap-14">
            <div className="space-y-6 motion-safe:animate-fade-up">
              {/* each arrow stays with the word after it, so a wrap never leaves an arrow alone at a line end */}
              <p className="flex flex-wrap gap-x-[0.6em] font-mono text-[11px] tracking-[0.1em] text-subtle uppercase sm:tracking-[0.16em]">
                <span>Photo</span>
                <span className="whitespace-nowrap">
                  <span className="text-dim">→</span> millimetres
                </span>
                <span className="whitespace-nowrap">
                  <span className="text-dim">→</span> program
                </span>
                <span className="whitespace-nowrap">
                  <span className="text-dim">→</span> <span className="text-accent-text">verified</span>
                </span>
              </p>
              <h1 className="text-[44px] leading-[0.98] font-semibold tracking-[-0.045em] text-fg sm:text-[60px] xl:text-[68px]">
                A broken plastic part in. A <span className="text-accent-text">proven</span> replacement out.
              </h1>
              <p className="max-w-xl text-[16px] leading-7 text-muted sm:text-[17px]">
                Millions of people own a 3D printer; almost none can design the part they need. Lay the broken part on your laptop
                screen and take a photo. PartSmith measures it in millimetres, writes it as a program with named knobs, and code checks
                the model against your photo before you print.
              </p>
              <div className="flex flex-wrap gap-2.5">
                <Button asChild variant="primary" size="lg">
                  <Link href="/fix">
                    Fix a broken part <ArrowRight aria-hidden />
                  </Link>
                </Button>
                <Button asChild variant="outline" size="lg">
                  <Link href="#film">
                    <PlayCircle aria-hidden /> Watch the film
                  </Link>
                </Button>
              </div>
              <p className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[13px] text-muted">
                <span>Or, with no part in hand:</span>
                <Link href="/jobs/demo" className="inline-flex items-center gap-1 underline-offset-2 hover:text-fg hover:underline">
                  <FlaskConical className="size-3.5" aria-hidden /> Try a sample
                </Link>
                <Link href="/describe" className="inline-flex items-center gap-1 underline-offset-2 hover:text-fg hover:underline">
                  <PenLine className="size-3.5" aria-hidden /> Describe a part
                </Link>
                <Link href="/playground" className="inline-flex items-center gap-1 underline-offset-2 hover:text-fg hover:underline">
                  <SlidersHorizontal className="size-3.5" aria-hidden /> Playground
                </Link>
              </p>
            </div>
            <div id="try" className="min-w-0 scroll-mt-24 page-in">
              <HeroModel />
            </div>
          </div>
          <div className="mt-7">
            <JudgePath />
          </div>
        </Container>
      </div>

      <Container className="pt-14 sm:pt-16">
        <div id="film" className="grid scroll-mt-24 items-start gap-8 lg:grid-cols-2">
          <div className="min-w-0 space-y-3">
            <h2 className="text-[22px] font-semibold tracking-[-0.02em]">The film</h2>
            <FilmEmbed />
          </div>
          <div className="min-w-0 space-y-3">
            <h2 className="text-[22px] font-semibold tracking-[-0.02em]">One recorded run, as a drawing</h2>
            <HeroFigure sheet={{ n: n("hero"), of: OF }} />
          </div>
        </div>
      </Container>

      <Container className="space-y-28 py-16 sm:space-y-32 sm:py-20">
        <Sheet id="proof" n={n("proof")} of={OF} kicker="Proof" title="Measured, not claimed." description="Three numbers from this server's bench report. Each says how many cases it covers and what it was checked against.">
          <ProofStrip bench={benchV} />
        </Sheet>

        <Sheet
          id="how"
          n={n("how")}
          of={OF}
          kicker="How it works"
          title="Five steps, from a photo to a checked part."
          description="One recorded run, step by step: the photo, the outline, the sizes, the program and the check."
          actions={
            <Button asChild variant="ghost" size="sm">
              <Link href="/how">
                The whole pipeline in plain words <ArrowRight aria-hidden />
              </Link>
            </Button>
          }
        >
          <FiveSheets />
        </Sheet>

        <Sheet
          id="loop"
          n={n("loop")}
          of={OF}
          kicker="The loop"
          title="Watch it fix itself."
          description="A stored run played back from its own event log. Each round the agent edits a knob, code re-measures, and the biggest gap shrinks until it is inside the limit."
        >
          <FixItself />
        </Sheet>

        <Sheet
          id="lie"
          n={n("lie")}
          of={OF}
          kicker="Honesty"
          title="A lying model, caught."
          description="We told a model to lie about its work. The verifier measured anyway, and the download check kept the part from shipping as verified."
          actions={
            <Button asChild variant="ghost" size="sm">
              <Link href="/judges">
                The judge path <ArrowRight aria-hidden />
              </Link>
            </Button>
          }
        >
          <LieStrip bench={benchV} />
        </Sheet>

        <Sheet
          id="program"
          n={n("program")}
          of={OF}
          kicker="Parametric"
          title="Every part is a program."
          description="Named, typed knobs instead of a frozen mesh. Change a knob and the server re-builds the part; the knob that sets a size is the one that was measured."
        >
          <ProgramSection />
        </Sheet>

        <Sheet
          id="buy"
          n={n("buy")}
          of={OF}
          kicker="Cost"
          title="Buy it, or print it?"
          description="For the recorded run on sheet 1: the closest price a web search could cite (matched by name, not the same part), against what the verified program takes to print."
        >
          <BuyOrPrintStrip />
        </Sheet>

        <Sheet
          id="review"
          n={n("review")}
          of={OF}
          kicker="Review"
          title="A person signs off."
          description="Code says whether the model matches the photo. A person says whether it is the right part — pins what is wrong, sends it back, and the next round is measured again."
        >
          <SignOff />
        </Sheet>

        <Sheet
          id="agents"
          n={n("agents")}
          of={OF}
          kicker="For agents"
          title="Your coding agent can use it too."
          description="Search the registry, ask for a variant in plain words and bake an STL, over REST or MCP."
        >
          <AgentsStrip />
        </Sheet>

        <ClosingCta sheet={{ n: n("cta"), of: OF }} />
      </Container>
    </>
  );
}
