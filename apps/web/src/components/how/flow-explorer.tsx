"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, ShieldCheck } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TermText } from "@/components/ui/term";
import { FLOW_STEPS, fetchFlowData, stepFacts, type FlowData, type FlowStep } from "@/lib/how-flow";
import { cn } from "@/lib/utils";

function Artifact({ step, data, pending }: { step: FlowStep; data?: FlowData; pending: boolean }) {
  if (step.id === "program") {
    return (
      <figure className="space-y-2">
        <div tabIndex={0} role="region" aria-label="Knob lines from the run's program" className="scrollbar-thin overflow-x-auto rounded-lg border border-border bg-surface-2 p-3">
          {data ? (
            <pre className="font-mono text-[11.5px] leading-[1.7] text-fg">{data.run.params.join("\n")}</pre>
          ) : pending ? (
            <Skeleton className="h-36" />
          ) : (
            <p className="text-[13px] text-muted">The program&apos;s lines did not load. They are on the run&apos;s job page.</p>
          )}
        </div>
        <figcaption className="text-[12px] leading-[1.4] text-subtle">Real lines from the run&apos;s part.py: name, value, smallest, largest, step, unit.</figcaption>
      </figure>
    );
  }
  return (
    <div className={cn("grid gap-3", step.images.length > 1 && "sm:grid-cols-2")}>
      {step.images.map((image) => (
        <figure key={image.src} className="space-y-2">
          {/* eslint-disable-next-line @next/next/no-img-element -- files saved from the run, shown as they are */}
          <img src={image.src} alt={image.alt} loading="lazy" className="max-h-[380px] w-full rounded-lg border border-border bg-paper object-contain" />
          <figcaption className="text-[12px] leading-[1.4] text-subtle">{image.caption}</figcaption>
        </figure>
      ))}
    </div>
  );
}

/** The whole path as eight steps you can walk through, on the recorded battery-cover run. */
export function FlowExplorer() {
  const [current, setCurrent] = React.useState(FLOW_STEPS[0]!.id);
  const data = useQuery({ queryKey: ["flow-data"], queryFn: ({ signal }) => fetchFlowData(signal), staleTime: Infinity });
  const index = FLOW_STEPS.findIndex((s) => s.id === current);
  const previous = FLOW_STEPS[index - 1];
  const next = FLOW_STEPS[index + 1];
  return (
    <Tabs value={current} onValueChange={setCurrent}>
      <TabsList aria-label="Steps from photo to file" className="grid grid-cols-4 gap-1.5 overflow-visible border-b-0 md:grid-cols-8">
        {FLOW_STEPS.map((step, i) => (
          <TabsTrigger
            key={step.id}
            value={step.id}
            className={cn(
              "flex h-auto min-w-0 flex-col items-start gap-0.5 rounded-md border px-2 py-1.5 text-left whitespace-normal",
              step.id === current ? "border-fg bg-surface text-fg" : "border-border text-muted hover:border-border-strong hover:text-fg",
            )}
          >
            <span className="font-mono text-[11px] text-subtle tnum">{i + 1}</span>
            <span className="text-[12.5px] leading-[1.2] font-medium">{step.short}</span>
          </TabsTrigger>
        ))}
      </TabsList>
      {FLOW_STEPS.map((step, i) => {
        const facts = data.data ? stepFacts(step.id, data.data) : [];
        return (
          <TabsContent key={step.id} value={step.id} className="pt-5">
            <div className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)] lg:gap-10">
              <div className="min-w-0 space-y-2.5">
                <Badge tone="neutral">recorded run · rendered sample photo</Badge>
                <Artifact step={step} data={data.data} pending={data.isPending} />
              </div>
              <div className="min-w-0 space-y-4">
                <div className="space-y-2">
                  <p className="font-mono text-[11.5px] text-subtle tnum">
                    Step {i + 1} of {FLOW_STEPS.length}
                  </p>
                  <h3 className="text-[19px] leading-tight font-semibold tracking-tight text-fg">{step.title}</h3>
                  <p className="text-[14px] leading-6 text-muted">
                    <TermText text={step.plain} />
                  </p>
                </div>
                {facts.length ? (
                  <ul className="space-y-1 border-l-2 border-border pl-3 text-[13px] leading-[1.5] text-fg" aria-label="This run's numbers">
                    {facts.map((fact) => (
                      <li key={fact}>
                        <TermText text={fact} />
                      </li>
                    ))}
                  </ul>
                ) : null}
                {data.isError && !facts.length ? <p className="text-[12.5px] text-subtle">The run&apos;s numbers did not load. The pictures are still the run&apos;s own.</p> : null}
                <div className="rounded-lg border border-ok-border bg-ok-soft/40 p-3">
                  <p className="flex items-center gap-1.5 text-[12.5px] font-semibold text-fg">
                    <ShieldCheck className="size-3.5 shrink-0 text-ok" aria-hidden /> Why this step can&apos;t be faked
                  </p>
                  <p className="mt-1 text-[13px] leading-[1.5] text-fg">
                    <TermText text={step.proof} />
                  </p>
                </div>
                <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]">
                  <span className="text-subtle">See it:</span>
                  {step.links.map((l) => (
                    <Link key={l.href} href={l.href} className="font-medium text-accent-text hover:underline">
                      {l.label}
                    </Link>
                  ))}
                  {data.data ? (
                    <Link href={`/jobs/${encodeURIComponent(data.data.run.id)}`} className="font-medium text-accent-text hover:underline">
                      This run&apos;s job page
                    </Link>
                  ) : null}
                </p>
                <div className="flex items-center justify-between gap-2 border-t border-border pt-3">
                  <Button variant="ghost" size="sm" disabled={!previous} onClick={() => previous && setCurrent(previous.id)}>
                    <ArrowLeft aria-hidden /> {previous ? previous.short : "Back"}
                  </Button>
                  <Button variant="outline" size="sm" disabled={!next} onClick={() => next && setCurrent(next.id)}>
                    {next ? next.short : "Last step"} <ArrowRight aria-hidden />
                  </Button>
                </div>
              </div>
            </div>
          </TabsContent>
        );
      })}
    </Tabs>
  );
}
