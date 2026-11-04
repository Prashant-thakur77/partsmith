"use client";

import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { Container, PageHeader, Section } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { BakedMesh } from "@/components/viewer/baked-mesh";
import { fetchLandscape, proofApi, type Landscape } from "@/lib/api-proof";
import { fetchBakedIndex, type BakedStar } from "@/lib/baked-models";
import { baseIndex, compareRows, meshScale, type Goal } from "@/lib/stretch";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";

const GOALS: { id: Goal; label: string; target: string }[] = [
  { id: "hole_d", label: "Bigger holes", target: "Target hole diameter" },
  { id: "length", label: "Longer plate", target: "Target plate length" },
];

function Stretch({ star }: { star: BakedStar }) {
  const [goal, setGoal] = React.useState<Goal>("hole_d");
  const steps = star.knobs[goal];
  const [picked, setPicked] = React.useState<number | null>(null);
  const index = picked ?? baseIndex(star, goal);
  const step = steps[Math.min(index, steps.length - 1)]!;
  const scale = meshScale(star, goal, step);
  const rows = compareRows(star, goal, step);
  const largest = Math.max(...star.knobs.length.map((s) => s.size_mm[0])) * 1.1;
  const meta = GOALS.find((g) => g.id === goal)!;
  const value = `${fmtNum(step.value)} mm`;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <div role="group" aria-label="What you want to change" className="inline-flex gap-1">
          {GOALS.map((g) => (
            <Button
              key={g.id}
              size="sm"
              variant={goal === g.id ? "primary" : "outline"}
              aria-pressed={goal === g.id}
              onClick={() => {
                setGoal(g.id);
                setPicked(null);
              }}
            >
              {g.label}
            </Button>
          ))}
        </div>
        <div className="min-w-[220px] flex-1 space-y-1">
          <div className="flex justify-between gap-2 text-[13px]">
            <span className="font-medium">{meta.target}</span>
            <span className="font-mono tnum">{value}</span>
          </div>
          <Slider
            aria-label={meta.target}
            aria-valuetext={value}
            value={[index]}
            min={0}
            max={steps.length - 1}
            step={1}
            onValueChange={([v]) => setPicked(v ?? 0)}
          />
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <figure className="overflow-hidden rounded-lg border border-border bg-surface">
          <figcaption className="border-b border-border px-3 py-2 text-[13px] font-medium">
            Stretch the mesh <span className="font-normal text-muted">(scaled in your browser)</span>
          </figcaption>
          <BakedMesh
            file={star.base.file}
            sizeMm={largest}
            scale={scale}
            view="under"
            turning={false}
            label={`The plate from behind, its mesh scaled to reach ${value}. ${rows.map((r) => `${r.what}: ${r.mesh}`).join(". ")}.`}
            className="h-[220px] bg-paper"
          />
        </figure>
        <figure className="overflow-hidden rounded-lg border border-border bg-surface">
          <figcaption className="border-b border-border px-3 py-2 text-[13px] font-medium">
            Turn the knob <span className="font-normal text-muted">(the program&apos;s real bake)</span>
          </figcaption>
          <BakedMesh
            file={step.file}
            sizeMm={largest}
            view="under"
            turning={false}
            label={`The plate from behind, rebuilt by its program at ${value}. ${rows.map((r) => `${r.what}: ${r.knob}`).join(". ")}.`}
            className="h-[220px] bg-paper"
          />
        </figure>
      </div>
      <div className="overflow-x-auto rounded-lg border border-border" tabIndex={0} role="region" aria-label="Stretching against the knob, in numbers">
        <table className="w-full min-w-[420px] text-left text-[13px]">
          <thead className="bg-surface-2 text-[12px] text-muted">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">At {value}</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Stretch the mesh</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Turn the knob</th>
            </tr>
          </thead>
          <tbody className="font-mono tnum">
            {rows.map((r) => (
              <tr key={r.what} className="border-t border-border">
                <td className="px-3 py-2 font-sans">{r.what}</td>
                <td className="px-3 py-2 text-right">{r.mesh}</td>
                <td className="px-3 py-2 text-right">{r.knob}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[12px] leading-[17px] text-subtle">
        A two-hole wall hook plate, seen from behind: a knob variant of a verified part. The left side is arithmetic on the mesh; the right side
        reads sizes measured on each bake. Real CadQuery output, baked ahead of time; the browser runs no CAD.
      </p>
    </div>
  );
}

function PeopleUse({ table }: { table: Landscape }) {
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto rounded-lg border border-border" tabIndex={0} role="region" aria-label="Comparison table">
        <table className="w-full min-w-[720px] text-left text-[13px]">
          <thead className="bg-surface-2 text-[12px] text-muted">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">Approach</th>
              {table.columns.map((c) => (
                <th key={c} scope="col" className="px-3 py-2 font-medium">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((r) => (
              <tr key={r.name} className={cn("border-t border-border align-top", r.ours && "bg-accent-soft")}>
                <th scope="row" className="px-3 py-2.5 text-left font-medium">
                  {r.name}
                  <span className="mt-0.5 block max-w-[280px] text-[12px] leading-[17px] font-normal text-muted">{r.why}</span>
                </th>
                {r.cells.map((c, i) => (
                  <td key={i} className="px-3 py-2.5">
                    {c}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[14px] font-medium">{table.finding}</p>
      <p className="text-[12.5px] leading-[18px] text-muted">
        <a href={table.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline-offset-2 hover:text-fg hover:underline">
          {table.source} <ExternalLink className="size-3" aria-hidden />
        </a>
        . Categories, not products: tools in a category differ. The PartSmith row is by design, and real phone captures are{" "}
        <Link href="/proof" className="underline underline-offset-2 hover:text-fg">
          not tested yet
        </Link>
        . What makes that row possible is SAM 3.1 used as a measuring instrument and Muse Spark Open writing the program on open weights:{" "}
        <Link href="/models" className="underline underline-offset-2 hover:text-fg">
          which AI did what
        </Link>
        .
      </p>
    </div>
  );
}

export function CompareClient() {
  const baked = useQuery({ queryKey: ["baked-index"], queryFn: ({ signal }) => fetchBakedIndex(signal), staleTime: Infinity });
  const table = useQuery({ queryKey: ["landscape"], queryFn: ({ signal }) => fetchLandscape(signal), staleTime: Infinity });
  const proof = useQuery({ queryKey: ["proof"], queryFn: proofApi.proof, retry: false });
  const bench = proof.data?.instruments.find((e) => e.id === "program_vs_mesh");
  return (
    <>
      <PageHeader
        eyebrow="Compare"
        title="Why a program, and how this differs"
        description="A scan gives you a mesh, and a mesh can only be stretched. PartSmith gives you a program with named knobs. Try both on the same real part."
      />
      <Container className="space-y-12 py-8">
        <Section id="stretch" title="Stretch a mesh, or turn a knob">
          {baked.isPending ? (
            <div role="status" aria-label="Loading the example part">
              <Skeleton className="h-96" />
            </div>
          ) : baked.isError || !baked.data.star ? (
            <ErrorState error={baked.error ?? new Error("The example part is not available")} what="the example part" onRetry={() => void baked.refetch()} />
          ) : (
            <Stretch star={baked.data.star} />
          )}
          {bench ? (
            <div className="rounded-lg border border-border bg-surface p-4">
              <p className="font-mono text-[22px] font-semibold tnum">{bench.headline}</p>
              <p className="text-[13.5px] text-muted">
                {bench.what}, over {bench.n} parts. {bench.detail}.
              </p>
              <p className="mt-1 font-mono text-[11.5px] text-subtle">
                {bench.source} · {bench.command}
              </p>
            </div>
          ) : null}
        </Section>
        <Section id="today" title="What people use today">
          {table.isPending ? (
            <div role="status" aria-label="Loading the comparison">
              <Skeleton className="h-72" />
            </div>
          ) : table.isError ? (
            <ErrorState error={table.error} what="the comparison" onRetry={() => void table.refetch()} />
          ) : (
            <PeopleUse table={table.data} />
          )}
        </Section>
      </Container>
    </>
  );
}
