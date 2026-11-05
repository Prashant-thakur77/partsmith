import { ArrowRight, Check, Minus, X } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { FlowExplorer } from "@/components/how/flow-explorer";
import { Container, PageHeader, Section } from "@/components/layout/page";
import { MatFigureStatic } from "@/components/art/mat-figure";
import { OrthoViews } from "@/components/art/ortho-views";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { COMPARE_COLUMNS, compareRows, type Cell, type CompareRow } from "@/lib/compare";
import { GLOSSARY as WORDS } from "@/lib/glossary";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: "How it works",
  description: "Eight steps from a phone photo of a broken part to a checked, printable replacement, on one recorded run's real files, and the words the site uses.",
};

const GLOSSARY: [string, string][] = [
  [WORDS.hausdorff.title, WORDS.hausdorff.text],
  [WORDS.iou.title, WORDS.iou.text],
  [WORDS.parametric.title, WORDS.parametric.text],
  [WORDS.verifier.title, WORDS.verifier.text],
  [WORDS.mat.title, WORDS.mat.text],
  ["Residual", "For one feature (a hole, an edge), the measured size minus the model's size, in millimetres."],
  ["Verified", "The code's check passed: the model is within the tolerance of the photo. A model cannot give itself this badge."],
  ["Best effort", "The agent's closest model did not pass the check. You can still see it and download it, clearly marked."],
  ["Recorded run (replay)", "A real run saved earlier and played back from its log. Nothing is re-computed and no model is called."],
  ["Mock", "A stand-in answer used when no model key is set. It shows how the pipeline flows, not what a model would say."],
  ["Synthetic", "A photo rendered by the computer from a known shape, so the true sizes are known exactly. Used for testing."],
];

export default async function HowPage() {
  // our real-photo cell follows the bench (real-part sample count); unreadable bench → the cell claims nothing
  const realN = await api.bench().then((b) => b.tables.real_ruler?.n ?? 0, () => null);
  const rows = compareRows(realN);
  return (
    <>
      <PageHeader
        eyebrow="How it works"
        title="From a phone photo to a part you can print"
        description="Eight steps. The AI suggests a model; plain code measures it against your photo and decides whether it is good enough."
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
        <Section
          id="steps"
          title="The eight steps"
          description="Click a step to see what happened in one recorded run: its real files and numbers, what the step does, and why it can't be faked."
        >
          <FlowExplorer />
        </Section>

        <Section id="drawings" title="The mat and the program, as drawings">
          <div className="grid gap-8 md:grid-cols-2 lg:gap-14">
            <figure className="space-y-2">
              <MatFigureStatic title="The screen mat: fiducial markers in the corners and along the top, a broken part lying in the middle" />
              <figcaption className="font-mono text-[11px] leading-4 text-subtle">Fig. A · the part on the screen mat (picture, no measurements).</figcaption>
            </figure>
            <figure className="space-y-2">
              <OrthoViews />
              <figcaption className="font-mono text-[11px] leading-4 text-subtle">Fig. B · what the program describes: every view of the part, drawn by the agent and checked by code.</figcaption>
            </figure>
          </div>
        </Section>

        <Section id="rule" title="The model proposes, code decides">
          <p className="max-w-2xl rounded-lg border border-border bg-surface p-5 text-[14px] leading-6 text-muted">
            The AI only ever suggests a model. Whether a part is called <span className="text-fg">verified</span> is decided by
            ordinary code that measures the model against your photo, and every number you see on this site comes from that code
            or from saved test reports, never from the AI&apos;s own claims.
          </p>
        </Section>

        <Section id="compare" title="How it compares" description="Kinds of tools, not products. Individual tools vary; this is the general picture.">
          <CompareTable rows={rows} />
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

const MARK_ICON = { yes: Check, no: X, partial: Minus } as const;

function CompareCell({ cell, ours }: { cell: Cell; ours: boolean }) {
  const Icon = cell.mark === "text" ? null : MARK_ICON[cell.mark];
  return (
    <td className={cn("px-3 py-2.5 align-top", ours && "bg-accent-soft/40")}>
      <span
        className={cn(
          "inline-flex items-center gap-1 text-[13px] font-medium",
          cell.mark === "yes" ? "text-ok" : cell.mark === "no" ? "text-subtle" : cell.mark === "partial" ? "text-warn" : "text-fg",
        )}
      >
        {Icon ? <Icon className="size-3.5 shrink-0" aria-hidden /> : null}
        {cell.label}
      </span>
      {cell.note ? <span className="mt-0.5 block text-[11.5px] leading-4 text-muted">{cell.note}</span> : null}
      {cell.href ? (
        <Link href={cell.href} className="mt-1 inline-block text-[11.5px] font-medium text-accent-text underline underline-offset-2">
          {cell.link ?? "More"}
        </Link>
      ) : null}
    </td>
  );
}

function CompareTable({ rows }: { rows: CompareRow[] }) {
  const last = COMPARE_COLUMNS.length - 1;
  return (
    <div className="scrollbar-thin max-w-full overflow-x-auto rounded-lg border border-border bg-surface" role="region" aria-labelledby="compare-caption" tabIndex={0}>
      <table className="w-full min-w-[760px] border-collapse text-left">
        <caption id="compare-caption" className="px-3 pt-3 pb-1 text-left text-[12px] text-subtle">
          What each kind of tool gives you for replacing a broken part. Yes, No or Partial, with a short note.
        </caption>
        <thead>
          <tr className="border-b border-border">
            <th scope="col" className="w-[22%] px-3 py-2 text-[12px] font-medium text-subtle">
              Feature
            </th>
            {COMPARE_COLUMNS.map((c, i) => (
              <th key={c} scope="col" className={cn("px-3 py-2 text-[12px] font-semibold", i === last ? "bg-accent-soft/40 text-fg" : "text-muted")}>
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.feature} className="border-b border-border last:border-b-0">
              <th scope="row" className="px-3 py-2.5 align-top text-[13px] font-medium text-fg">
                {r.feature}
              </th>
              {r.cells.map((cell, i) => (
                <CompareCell key={COMPARE_COLUMNS[i]} cell={cell} ours={i === last} />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
