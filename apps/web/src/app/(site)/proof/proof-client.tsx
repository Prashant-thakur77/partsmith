"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertCircle, ExternalLink } from "lucide-react";
import Link from "next/link";
import { Container, PageHeader, Section } from "@/components/layout/page";
import { Badge } from "@/components/ui/badge";
import { CopyButton } from "@/components/ui/copy-button";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { proofApi, rateText, type Proof, type ProofEntry, type ScaleReport } from "@/lib/api-proof";
import { REPO_URL } from "@/lib/site-links";

const fileUrl = (path: string) => `${REPO_URL}/blob/main/${path}`;

function EvidenceCard({ e }: { e: ProofEntry }) {
  return (
    <li className="flex h-full flex-col gap-3 rounded-lg border border-border bg-surface p-4">
      <div>
        <h3 className="text-[13px] font-medium text-muted">{e.title}</h3>
        <p className="mt-1 font-mono text-[24px] leading-8 font-semibold tracking-tight tnum">{e.headline ?? "not run"}</p>
        <p className="text-[13px] text-muted">{e.what}</p>
      </div>
      <dl className="space-y-1.5 text-[12.5px] leading-[18px]">
        <div>
          <dt className="inline font-medium">Sample: </dt>
          <dd className="inline text-muted">
            n = {e.n ?? "–"}
            {e.ci ? ` · ${e.ci_of ?? "interval"} ${e.ci}` : ""}
          </dd>
        </div>
        <div>
          <dt className="inline font-medium">Checked against: </dt>
          <dd className="inline text-muted">{e.ground_truth}</dd>
        </div>
        <div>
          <dt className="inline font-medium">What it is: </dt>
          <dd className="inline text-muted">{e.label}</dd>
        </div>
        {e.detail ? (
          <div>
            <dt className="inline font-medium">Also: </dt>
            <dd className="inline text-muted">{e.detail}</dd>
          </div>
        ) : null}
      </dl>
      <div className="mt-auto space-y-1.5 border-t border-border pt-2.5">
        <div className="flex items-center justify-between gap-2">
          <code className="min-w-0 truncate font-mono text-[11.5px] text-muted" title={e.command}>
            {e.command}
          </code>
          <CopyButton value={e.command} label="Copy" />
        </div>
        <a href={fileUrl(e.source)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-mono text-[11.5px] text-subtle hover:text-fg">
          {e.source} <ExternalLink className="size-3" aria-hidden />
        </a>
      </div>
    </li>
  );
}

function Grid({ entries }: { entries: ProofEntry[] }) {
  return <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">{entries.map((e) => <EvidenceCard key={e.id} e={e} />)}</ul>;
}

function NotTested({ n }: { n: Proof["not_tested"] }) {
  const rows = [
    { what: "Real phone photos of a part on a laptop screen, measured", value: n.real_phone_photos_measured },
    { what: "Real parts checked against a ruler", value: n.real_parts_with_ruler_ground_truth },
    { what: "Real prints or repairs logged", value: n.real_prints_or_repairs_logged },
    { what: "Review rounds decided by a person", value: n.person_reviewed_rounds },
  ];
  return (
    <section aria-labelledby="not-tested-title" className="rounded-lg border border-warn-border bg-warn-soft p-4 sm:p-5">
      <h2 id="not-tested-title" className="flex items-center gap-2 text-[15px] font-semibold">
        <AlertCircle className="size-4" aria-hidden /> Not tested yet
      </h2>
      <p className="mt-1 max-w-3xl text-[13.5px] leading-6 text-muted">
        Everything below comes from rendered photos, public photos and scripted attacks, run through live models and stored. These
        counts come from the same reports and stay at what they are until real captures exist.
      </p>
      <ul className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {rows.map((r) => (
          <li key={r.what} className="rounded-md border border-warn-border bg-surface p-3">
            <span className="block font-mono text-[22px] font-semibold tnum">{r.value}</span>
            <span className="text-[12.5px] leading-[18px] text-muted">{r.what}</span>
          </li>
        ))}
      </ul>
      {n.scripted_review_decisions ? (
        <p className="mt-2 text-[12.5px] text-muted">{n.scripted_review_decisions} scripted review decisions exist; they are labelled as tests and not counted as a person&apos;s.</p>
      ) : null}
    </section>
  );
}

function Audit({ rows }: { rows: Proof["audit"] }) {
  const verified = rows.reduce((a, r) => a + r.verified, 0);
  const within = rows.reduce((a, r) => a + r.within, 0);
  return (
    <div className="space-y-2">
      <p className="max-w-3xl text-[13.5px] leading-6 text-muted">
        Verified means the model matches the photos it was given. Here is every verified part checked against ground truth on every size:{" "}
        {within} of {verified} were within 0.5 mm on all of them. Height from a top photo alone is the usual miss, which is why a side photo helps.
      </p>
      <div className="overflow-x-auto rounded-lg border border-border" tabIndex={0} role="region" aria-label="Verified parts against ground truth">
        <table className="w-full min-w-[520px] text-left text-[13px]">
          <thead className="bg-surface-2 text-[12px] text-muted">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">Suite</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Full-loop runs</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Verified</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Within 0.5 mm</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Over 0.5 mm off</th>
            </tr>
          </thead>
          <tbody className="font-mono tnum">
            {rows.map((r) => (
              <tr key={r.suite} className="border-t border-border">
                <td className="px-3 py-2 font-sans">{r.suite}</td>
                <td className="px-3 py-2 text-right">{r.runs}</td>
                <td className="px-3 py-2 text-right">{r.verified}</td>
                <td className="px-3 py-2 text-right">{r.within}</td>
                <td className="px-3 py-2 text-right">{r.off}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Gates({ tests }: { tests: Proof["tests"] }) {
  if (!tests.gates.length) return <p className="text-[13.5px] text-muted">The test report has not been generated on this server yet.</p>;
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-lg border border-border" tabIndex={0} role="region" aria-label="Test suites table">
        <table className="w-full min-w-[620px] text-left text-[13px]">
          <thead className="bg-surface-2 text-[12px] text-muted">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">Gate</th>
              <th scope="col" className="px-3 py-2 font-medium">Status</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Passed</th>
              <th scope="col" className="px-3 py-2 font-medium">Command</th>
            </tr>
          </thead>
          <tbody>
            {tests.gates.map((g) => (
              <tr key={g.id} className="border-t border-border">
                <td className="px-3 py-2">{g.title}</td>
                <td className="px-3 py-2">
                  <Badge tone={g.status === "passed" ? "ok" : g.status === "failed" ? "bad" : "neutral"}>{g.status}</Badge>
                </td>
                <td className="px-3 py-2 text-right font-mono tnum">
                  {g.tests != null ? `${g.passed}/${g.tests}` : "–"}
                  {g.skipped ? <span className="text-muted"> ({g.skipped} skipped)</span> : null}
                </td>
                <td className="px-3 py-2 font-mono text-[11.5px] text-muted">{g.command ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="font-mono text-[11.5px] text-subtle">
        {tests.git ? `commit ${tests.git.slice(0, 7)} · ` : ""}
        {tests.generated_at ?? ""} ·{" "}
        <a href={fileUrl(tests.source)} target="_blank" rel="noreferrer" className="hover:text-fg">
          {tests.source}
        </a>
      </p>
    </div>
  );
}

/** One line of the large evaluation; absent when that part did not run. */
function ScaleRow({ what, headline, ci, note }: { what: string; headline?: string | null; ci?: string | null; note?: string | null }) {
  if (!headline) return null;
  return (
    <li className="rounded-lg border border-border bg-surface p-3">
      <p className="font-mono text-[20px] font-semibold tnum">{headline}</p>
      <p className="text-[13px] text-muted">{what}</p>
      {ci ? <p className="font-mono text-[11.5px] text-subtle">95 % interval {ci}</p> : null}
      {note ? <p className="mt-1 text-[12px] leading-[17px] text-subtle">{note}</p> : null}
    </li>
  );
}

function Scale({ s }: { s: ScaleReport }) {
  const runs = Object.values(s.runs ?? {}).reduce((a, b) => a + b, 0);
  const planned = Object.values(s.planned ?? {}).reduce((a, b) => a + b, 0);
  const paired = s.paired_b1_vs_ps;
  const off = s.verified_but_off;
  const family = rateText(s.understanding?.family_correct);
  const broken = rateText(s.understanding?.broken_region_found);
  const wonder = rateText(s.wonder?.accepted_with_citation);
  const spoken = rateText(s.voice?.spoken);
  const presets = Object.entries(s.sam?.by_preset ?? {});
  const top = rateText(off?.top_only);
  const side = rateText(off?.top_and_side);
  return (
    <div className="space-y-3">
      <p className="max-w-3xl text-[13.5px] leading-6 text-muted">
        Fresh live runs on new rendered samples, with sizes fixed in a written plan before anything ran: {runs} of {planned} planned runs
        finished{s.usd?.total != null ? ` for $${s.usd.total}` : ""}. Failures stay in. None of this is a phone capture.
      </p>
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <ScaleRow
          what={`single shot against the full loop, passing within 0.5 mm, ${paired?.n_pairs ?? 0} pairs`}
          headline={paired ? `${paired.b1_pass} → ${paired.ps_pass}` : null}
          note={paired?.p_value != null ? `paired test p = ${paired.p_value}` : null}
        />
        <ScaleRow
          what="verified parts over 0.5 mm off, all full-loop runs"
          headline={off?.all_ps ? `${off.all_ps.k} of ${off.all_ps.n}` : null}
          note={off?.all_ps?.off_in_height != null ? `${off.all_ps.off_in_height} of those were height` : null}
        />
        <ScaleRow what="verified but off, intact parts, top photo only" headline={top?.headline} ci={top?.ci} />
        <ScaleRow what="verified but off, intact parts, top and side photos" headline={side?.headline} ci={side?.ci} />
        <ScaleRow what="Muse Spark named the right part family" headline={family?.headline} ci={family?.ci} />
        <ScaleRow what="Muse Spark found the break on broken parts" headline={broken?.headline} ci={broken?.ci} />
        {presets.slice(0, 3).map(([name, p]) => (
          <ScaleRow
            key={name}
            what={`SAM 3.1 median overlap with true mask, ${name.replaceAll("_", " ")}, n = ${p.n}`}
            headline={p.iou_median != null ? String(p.iou_median) : null}
            note={p.boundary_mean_mm_median != null ? `median boundary error ${p.boundary_mean_mm_median} mm` : null}
          />
        ))}
        <ScaleRow what="Muse Wonder lookups where code accepted a cited value" headline={wonder?.headline} ci={wonder?.ci} />
        <ScaleRow what="spoken Hindi and English edits that made the right change" headline={spoken?.headline} ci={spoken?.ci} note={s.voice?.speech ? `Speech: ${s.voice.speech}` : null} />
      </ul>
      <p className="font-mono text-[11.5px] text-subtle">
        <a href={fileUrl(s.source)} target="_blank" rel="noreferrer" className="hover:text-fg">
          {s.source}
        </a>{" "}
        · {s.command}
      </p>
    </div>
  );
}

export function ProofClient() {
  const q = useQuery({ queryKey: ["proof"], queryFn: proofApi.proof });
  return (
    <>
      <PageHeader
        eyebrow="Proof"
        title="What has been tested, and what hasn't"
        description="Every number here is read from a report file in the repo. Each result names what it was checked against and the command that reproduces it."
      />
      <Container className="space-y-10 py-8">
        {q.isPending ? (
          <div role="status" aria-label="Loading the evidence" className="space-y-3">
            <Skeleton className="h-36" />
            <Skeleton className="h-64" />
          </div>
        ) : q.isError ? (
          <ErrorState error={q.error} what="the evidence" onRetry={() => void q.refetch()} />
        ) : (
          <>
            <NotTested n={q.data.not_tested} />
            {q.data.outcomes.length ? (
              <Section id="outcomes" title="Did it do the right thing?" description="Situations with a known right answer.">
                <Grid entries={q.data.outcomes} />
              </Section>
            ) : null}
            {q.data.errors.length ? (
              <Section id="errors" title="How close is the part?" description="Error in millimetres against known sizes.">
                <Grid entries={q.data.errors} />
              </Section>
            ) : null}
            {q.data.instruments.length ? (
              <Section
                id="instruments"
                title="Do the measuring and the program hold up?"
                actions={
                  <Link href="/compare" className="text-[13px] text-muted underline-offset-2 hover:text-fg hover:underline">
                    Try stretch against knob yourself
                  </Link>
                }
              >
                <Grid entries={q.data.instruments} />
              </Section>
            ) : null}
            {q.data.audit.length ? (
              <Section id="audit" title="Every verified part against ground truth">
                <Audit rows={q.data.audit} />
              </Section>
            ) : null}
            {q.data.scale ? (
              <Section id="scale" title="The large evaluation">
                <Scale s={q.data.scale} />
              </Section>
            ) : null}
            <Section id="tests" title="Test suites" description="From the last run of `make proof`. A suite that did not run says so.">
              <Gates tests={q.data.tests} />
            </Section>
          </>
        )}
      </Container>
    </>
  );
}
