import { ArrowRight } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { Container, PageHeader, Section } from "@/components/layout/page";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = {
  title: "How it works",
  description: "Five steps from a phone photo of a broken part to a checked, printable replacement, and the words the site uses.",
};

type Step = { title: string; body: string; see: { href: string; label: string }[] };

const STEPS: Step[] = [
  {
    title: "Photo on the screen mat",
    body: "Open the mat on a laptop or tablet, lay the broken part on it and take a photo from above. The black squares around the edge are printed at a known size, so the photo carries its own ruler. No caliper, no printer.",
    see: [
      { href: "/mat", label: "Screen mat" },
      { href: "/calibrate", label: "Calibrate your screen" },
    ],
  },
  {
    title: "Photo becomes millimetres",
    body: "Code finds the squares, flattens the photo so it is seen straight on, and an image model traces the part's outline. Every length after this point is in millimetres, measured from pixels by code.",
    see: [{ href: "/judges", label: "Watch a recorded run" }],
  },
  {
    title: "An AI agent writes the CAD",
    body: "A language model writes a short CAD program for the part, with named knobs such as length or hole size. It is a program, not a frozen mesh, so you can change a size later and get a new file.",
    see: [{ href: "/models", label: "Which AI did what" }],
  },
  {
    title: "Code checks it against the photo",
    body: "A checker renders the model from above, lays its outline over the photo's outline and measures the biggest gap. If the gap is too big, the agent gets the numbers back and tries again. Only this check can mark a part verified.",
    see: [
      { href: "/results", label: "Accuracy" },
      { href: "/lessons", label: "What it learned" },
    ],
  },
  {
    title: "A person reviews it",
    body: "A person looks at the photo, the model and the checker's numbers, and can send it back with a note. Then you download STL, 3MF or STEP to print, and the part joins an open registry that people and AI agents can search.",
    see: [
      { href: "/review", label: "Review" },
      { href: "/parts", label: "Parts" },
      { href: "/agents", label: "For developers" },
    ],
  },
];

const GLOSSARY: [string, string][] = [
  ["Hausdorff (the gap)", "The biggest gap between the photo's outline and the model's outline, in millimetres. Smaller is better."],
  ["IoU", "How much the two outlines overlap: 1 means they cover exactly the same area, 0 means they do not touch."],
  ["Residual", "For one feature (a hole, an edge), the measured size minus the model's size, in millimetres."],
  ["Verified", "The code's check passed: the model is within the tolerance of the photo. A model cannot give itself this badge."],
  ["Best effort", "The agent's closest model did not pass the check. You can still see it and download it, clearly marked."],
  ["Recorded run (replay)", "A real run saved earlier and played back from its log. Nothing is re-computed and no model is called."],
  ["Mock", "A stand-in answer used when no model key is set. It shows how the pipeline flows, not what a model would say."],
  ["Synthetic", "A photo rendered by the computer from a known shape, so the true sizes are known exactly. Used for testing."],
];

export default function HowPage() {
  return (
    <>
      <PageHeader
        eyebrow="How it works"
        title="From a phone photo to a part you can print"
        description="Five steps. The AI suggests a model; plain code measures it against your photo and decides whether it is good enough."
        actions={
          <>
            <Button asChild variant="primary">
              <Link href="/fix">
                Fix a part <ArrowRight aria-hidden />
              </Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/jobs/demo">Try a sample</Link>
            </Button>
          </>
        }
      />
      <Container className="space-y-16 py-12">
        <Section id="steps" title="The five steps">
          <ol className="relative space-y-0">
            {STEPS.map((s, i) => (
              <li key={s.title} className="grid grid-cols-[2.25rem_minmax(0,1fr)] gap-x-4 pb-8 last:pb-0">
                <div className="flex flex-col items-center">
                  <span className="flex size-9 items-center justify-center rounded-full border border-border-strong bg-surface font-mono text-[13px] text-fg tnum">
                    {i + 1}
                  </span>
                  {i < STEPS.length - 1 ? <span aria-hidden className="mt-2 w-px flex-1 bg-border" /> : null}
                </div>
                <div className="space-y-2 pt-1.5">
                  <h3 className="text-[15px] font-semibold tracking-tight text-fg">{s.title}</h3>
                  <p className="max-w-2xl text-[14px] leading-6 text-muted">{s.body}</p>
                  <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]">
                    <span className="text-subtle">See it:</span>
                    {s.see.map((l) => (
                      <Link key={l.href} href={l.href} className="font-medium text-accent-text hover:underline">
                        {l.label}
                      </Link>
                    ))}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </Section>

        <Section id="rule" title="The model proposes, code decides">
          <p className="max-w-2xl rounded-lg border border-border bg-surface p-5 text-[14px] leading-6 text-muted">
            The AI only ever suggests a model. Whether a part is called <span className="text-fg">verified</span> is decided by
            ordinary code that measures the model against your photo, and every number you see on this site comes from that code
            or from saved test reports, never from the AI&apos;s own claims.
          </p>
        </Section>

        <Section id="words" title="Words used on this site">
          <dl className="grid gap-x-8 gap-y-5 sm:grid-cols-2">
            {GLOSSARY.map(([term, def]) => (
              <div key={term} className="border-t border-border pt-3">
                <dt className="text-[14px] font-medium text-fg">{term}</dt>
                <dd className="mt-1 text-[13.5px] leading-6 text-muted">{def}</dd>
              </div>
            ))}
          </dl>
        </Section>
      </Container>
    </>
  );
}
