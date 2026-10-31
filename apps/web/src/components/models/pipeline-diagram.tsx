import { ArrowDown, ArrowRight, RotateCcw } from "lucide-react";
import { ModeBadge } from "@/components/ui/provenance";
import type { ProviderStatus } from "@/lib/api-types";
import { cn } from "@/lib/utils";

/** One step of the photo → part pipeline: a model stage (read from /status) or a step that is plain code or a person. */
type Step = { stage: string; what: string } | { code: string; what: string } | { person: string; what: string };

export const FIX_PIPELINE: Step[] = [
  { person: "Photo on the mat", what: "A phone photo of the part on the laptop screen" },
  { stage: "segment", what: "Cuts the part out of the photo" },
  { code: "Markers → millimetres", what: "Screen markers set the scale; code measures" },
  { stage: "understand", what: "Names the part and its features" },
  { stage: "plan", what: "Picks a part program and its knobs" },
  { stage: "build", what: "Writes the CadQuery program" },
  { code: "Sandbox + verifier", what: "Runs the program, compares it with the photo" },
  { stage: "fix", what: "Reads the gaps and edits the program" },
  { stage: "judge", what: "Looks at photo and model; can only block" },
  { person: "Person reviews", what: "Accepts, or pins what is wrong and sends it back" },
  { code: "Registry", what: "Published with its knobs, numbers and files" },
];

/** A colour per model family, so the same model reads the same everywhere on the diagram. */
export function modelTone(model: string): string {
  const m = model.toLowerCase();
  if (m.includes("sam")) return "border-l-info";
  if (m.includes("glimmer")) return "border-l-warn";
  if (m.includes("open")) return "border-l-ok";
  if (m.includes("spark")) return "border-l-accent";
  return "border-l-border-strong";
}

function Node({ step, rows }: { step: Step; rows: Map<string, ProviderStatus> }) {
  if ("stage" in step) {
    const p = rows.get(step.stage);
    return (
      <div className={cn("h-full rounded-lg border border-l-4 border-border bg-surface p-3", modelTone(p?.model ?? ""))}>
        <div className="flex items-center justify-between gap-2">
          <span className="text-[13px] font-medium">{p?.role ?? step.stage}</span>
          {p ? <ModeBadge mode={p.mode} /> : null}
        </div>
        <div className="mt-1 truncate font-mono text-[11.5px] text-muted" title={p?.model}>
          {p ? p.model : "not on this server"}
        </div>
        <p className="mt-1.5 text-[12px] leading-snug text-subtle">{step.what}</p>
      </div>
    );
  }
  const label = "code" in step ? step.code : step.person;
  return (
    <div className="h-full rounded-lg border border-dashed border-border-strong bg-surface-2 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-[13px] font-medium">{label}</span>
        <span className="text-[10.5px] font-medium uppercase tracking-wide text-subtle">{"code" in step ? "code" : "person"}</span>
      </div>
      <p className="mt-1.5 text-[12px] leading-snug text-subtle">{step.what}</p>
    </div>
  );
}

/** The fix pipeline as boxes and arrows, each model step coloured by the model /status says runs it right now. */
export function PipelineDiagram({ providers }: { providers: ProviderStatus[] }) {
  const rows = new Map(providers.map((p) => [p.stage, p]));
  const models = [...new Set(FIX_PIPELINE.flatMap((s) => ("stage" in s && rows.get(s.stage) ? [rows.get(s.stage)!.model] : [])))];
  return (
    <figure className="space-y-4">
      <ol className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4" aria-label="Pipeline steps, in order">
        {FIX_PIPELINE.map((step, i) => (
          <li key={i} className="relative flex flex-col gap-1">
            <div className="flex items-center gap-1.5 font-mono text-[11px] text-subtle">
              <span className="tnum">{String(i + 1).padStart(2, "0")}</span>
              {"stage" in step && step.stage === "fix" ? (
                <span className="inline-flex items-center gap-1">
                  <RotateCcw className="size-3" aria-hidden /> loops back to step 07 until the gap is within the limit
                </span>
              ) : null}
            </div>
            <Node step={step} rows={rows} />
            {i < FIX_PIPELINE.length - 1 ? (
              <>
                <ArrowDown className="mx-auto size-4 text-subtle sm:hidden" aria-hidden />
                <ArrowRight className="absolute top-1/2 -right-2 hidden size-4 text-subtle sm:block" aria-hidden />
              </>
            ) : null}
          </li>
        ))}
      </ol>
      <figcaption className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted">
        {models.map((m) => (
          <span key={m} className={cn("border-l-4 pl-1.5 font-mono", modelTone(m))}>
            {m}
          </span>
        ))}
        <span className="border-l-4 border-dashed border-l-border-strong pl-1.5">dashed = code or a person, no model</span>
      </figcaption>
    </figure>
  );
}
