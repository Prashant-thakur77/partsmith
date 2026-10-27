import { ArrowRight, GitFork, Layers } from "lucide-react";
import Link from "next/link";
import { Fact, Section } from "@/components/layout/page";
import { PartCard, PartCardSkeleton } from "@/components/registry/part-card";
import { Button } from "@/components/ui/button";
import { Card, CardContent, Eyebrow } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { ModeBadge, OriginBadge } from "@/components/ui/provenance";
import type { PartCard as PartCardT, PartRecord } from "@/lib/api-types";
import { fmtNum, paramLabel, shortSha, titleCase } from "@/lib/format";

/**
 * Provenance, lineage, knob reference and matching parts. No hooks: rendered on the server when the part was fetched
 * there (no client JS), or inside the client page as a fallback. `matching`: list, null while loading, or the error.
 */
export function PartDetails({ part, matching }: { part: PartRecord; matching: PartCardT[] | null | unknown }) {
  return (
    <>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <Section title="Provenance">
            <Card>
              <CardContent className="pt-4">
                <dl>
                  <Fact label="Origin">
                    <OriginBadge origin={part.provenance.origin} />
                  </Fact>
                  <Fact label="Models">
                    <ModeBadge mode={part.provenance.provider_mode} />
                  </Fact>
                  {part.provenance.builder_model ? (
                    <Fact label="Builder model">
                      <span className="font-mono text-[12px]">{part.provenance.builder_model}</span>
                    </Fact>
                  ) : null}
                  {part.provenance.job_id ? (
                    <Fact label="Fix job">
                      <Link href={`/jobs/${encodeURIComponent(part.provenance.job_id)}`} className="font-mono text-[12px] text-accent-text hover:underline">
                        {part.provenance.job_id}
                      </Link>
                    </Fact>
                  ) : null}
                  <Fact label="Code sha">
                    <span className="font-mono text-[12px]">{shortSha(part.code_sha, 12)}</span>
                  </Fact>
                  <Fact label="Created by">{part.provenance.created_by}</Fact>
                  {part.provenance.note ? <Fact label="Note">{part.provenance.note}</Fact> : null}
                </dl>
              </CardContent>
            </Card>
          </Section>
          <Section title="Lineage">
            {part.lineage.length || part.provenance.forked_from ? (
              <ol className="space-y-2">
                {part.provenance.forked_from && !part.lineage.some((l) => l.relation === "forked_from") ? (
                  <li className="flex items-center gap-2 text-[13px]">
                    <GitFork className="size-4 text-muted" aria-hidden /> Forked from{" "}
                    <Link href={`/parts/${encodeURIComponent(part.provenance.forked_from)}`} className="font-mono text-accent-text hover:underline">
                      {part.provenance.forked_from}
                    </Link>
                  </li>
                ) : null}
                {part.lineage.map((l) => (
                  <li key={`${l.relation}-${l.slug}`} className="flex items-center gap-3 rounded-md border border-border bg-surface px-3 py-2 text-[13px]">
                    <GitFork className="size-4 shrink-0 text-muted" aria-hidden />
                    <span className="shrink-0 text-muted">{l.relation === "forked_from" ? "Forked from" : "Variant"}</span>
                    <Link href={`/parts/${encodeURIComponent(l.slug)}`} className="min-w-0 truncate font-medium text-accent-text hover:underline">
                      {l.title || l.slug}
                    </Link>
                    <span className="ml-auto shrink-0 font-mono text-[12px] text-subtle">v{l.version}</span>
                  </li>
                ))}
              </ol>
            ) : (
              <EmptyState compact title="Original part" icon={GitFork}>
                Not forked from another part.
              </EmptyState>
            )}
            <div className="space-y-2">
              <Eyebrow>Knob reference</Eyebrow>
              <div tabIndex={0} role="region" aria-label="Knob reference" className="overflow-x-auto rounded-md border border-border">
                <table className="w-full min-w-[420px] text-[12px]">
                  <caption className="sr-only">Knobs with ranges</caption>
                  <thead className="bg-surface-2 text-left text-[11px] text-subtle">
                    <tr>
                      <th scope="col" className="px-3 py-2 font-medium">Knob</th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">Default</th>
                      <th scope="col" className="px-3 py-2 text-right font-medium">Range</th>
                      <th scope="col" className="px-3 py-2 font-medium">Fit</th>
                    </tr>
                  </thead>
                  <tbody className="font-mono tnum">
                    {part.params.map((p) => (
                      <tr key={p.name} className="border-t border-border">
                        <th scope="row" className="px-3 py-2 text-left font-normal">
                          {p.name} <span className="font-sans text-subtle">{paramLabel(p.name, p.label) !== p.name ? `· ${paramLabel(p.name, p.label)}` : ""}</span>
                        </th>
                        <td className="px-3 py-2 text-right">
                          {fmtNum(p.default, p.topology ? 0 : 2)} {p.unit}
                        </td>
                        <td className="px-3 py-2 text-right text-muted">
                          {fmtNum(p.min, p.topology ? 0 : 2)}–{fmtNum(p.max, p.topology ? 0 : 2)}
                        </td>
                        <td className="px-3 py-2 font-sans text-muted">{p.topology ? "topology" : p.affects_fit ? "affects fit" : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </Section>
        </div>

        <Section
          id="matching"
          title="Matching parts"
          description="Same family or the same mating interface."
          actions={
            <Button asChild variant="ghost" size="sm">
              <Link href={`/parts?family=${encodeURIComponent(part.family)}`}>
                More {titleCase(part.family).toLowerCase()} parts <ArrowRight aria-hidden />
              </Link>
            </Button>
          }
        >
          {matching === null ? (
            <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
              {[0, 1, 2, 3].map((i) => (
                <PartCardSkeleton key={i} />
              ))}
            </div>
          ) : !Array.isArray(matching) ? (
            <ErrorState error={matching} compact what="matching parts" />
          ) : matching.length === 0 ? (
            <EmptyState compact title="No matching parts yet" icon={Layers} />
          ) : (
            <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
              {matching.slice(0, 8).map((p) => (
                <PartCard key={p.slug} part={p} />
              ))}
            </div>
          )}
        </Section>
    </>
  );
}
