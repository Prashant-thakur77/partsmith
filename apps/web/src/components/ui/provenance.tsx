import { BookOpen, Bot, FlaskConical, History, Ruler, ScanLine, Sparkles, UserRound, Wand2, Box } from "lucide-react";
import type { Citation, DataOrigin, ProviderMode, Source } from "@/lib/api-types";
import { runModesText, type RunModes } from "@/lib/job-cost";
import { Badge } from "./badge";
import { Tooltip } from "./tooltip";

const SOURCE: Record<Source, { label: string; tip: string; icon: typeof Ruler; tone: "neutral" | "info" | "warn" }> = {
  measured: { label: "measured", tip: "Measured by code from the photo on the calibrated mat.", icon: Ruler, tone: "neutral" },
  user_stated: { label: "you said", tip: "A value you typed or said. Used as given.", icon: UserRound, tone: "info" },
  inferred: { label: "inferred", tip: "Not visible in the photo; proposed by the model and checked against the rest of the part.", icon: Wand2, tone: "warn" },
  cited: { label: "cited", tip: "Found by a model with web search, with a citation. Never overrides a measured value.", icon: BookOpen, tone: "info" },
};

export function SourceBadge({ source }: { source: Source }) {
  const s = SOURCE[source];
  const Icon = s.icon;
  return (
    <Tooltip content={s.tip}>
      <Badge tone={s.tone} tabIndex={0} className="cursor-help">
        <Icon aria-hidden />
        {s.label}
      </Badge>
    </Tooltip>
  );
}

const ORIGIN: Record<DataOrigin, { label: string; tip: string; icon: typeof Ruler }> = {
  real: { label: "real photo", tip: "From a real phone photo of a real part.", icon: ScanLine },
  synthetic: { label: "synthetic", tip: "Rendered test input with exact ground truth — not a real photo.", icon: FlaskConical },
  reference_object: { label: "reference object", tip: "A standard object with published dimensions (e.g. an ID-1 card).", icon: Box },
  replay: { label: "replay", tip: "A recorded run played back. Nothing is recomputed live.", icon: History },
};

/** `plain`: no focusable tooltip (the tip goes in `title`), for use inside a button or link. */
export function OriginBadge({ origin, hideReal = false, plain = false }: { origin: DataOrigin; hideReal?: boolean; plain?: boolean }) {
  if (hideReal && origin === "real") return null;
  const o = ORIGIN[origin];
  const Icon = o.icon;
  if (plain)
    return (
      <Badge tone={origin === "real" ? "outline" : "mock"} title={o.tip}>
        <Icon aria-hidden />
        {o.label}
      </Badge>
    );
  return (
    <Tooltip content={o.tip}>
      <Badge tone={origin === "real" ? "outline" : "mock"} tabIndex={0} className="cursor-help">
        <Icon aria-hidden />
        {o.label}
      </Badge>
    </Tooltip>
  );
}

export function ModeBadge({ mode, hideLive = false }: { mode: ProviderMode | string; hideLive?: boolean }) {
  if (hideLive && mode === "live") return null;
  const tip =
    mode === "live"
      ? "Real model calls."
      : mode === "mock"
        ? "Deterministic mock — no API key was configured. Not model output."
        : mode === "replay"
          ? "Recorded model responses played back."
          : `Provider mode: ${mode}`;
  return (
    <Tooltip content={tip}>
      <Badge tone={mode === "live" ? "accent" : "mock"} upper tabIndex={0} className="cursor-help">
        {mode === "live" ? <Sparkles aria-hidden /> : <Bot aria-hidden />}
        {mode}
      </Badge>
    </Tooltip>
  );
}

const MODELS: Record<string, string> = { live: "live models", mock: "mock models", replay: "recorded model answers" };

/**
 * One chip for where a run's model answers came from, so "REPLAY" never sits next to "LIVE" on the same card:
 *  - `recorded`: a stored run played back → "Recorded run · live models" / "Recorded run · mock models";
 *  - `finished` (not recorded): a run that already ended → "live models" (they were live then, not now);
 *  - otherwise the calls are happening now → the LIVE / MOCK chip.
 */
export function RunBadge({
  mode: summaryMode,
  recorded = false,
  finished = false,
  plain = false,
  modes = null,
}: {
  mode: ProviderMode | string;
  recorded?: boolean;
  finished?: boolean;
  /** No focusable tooltip (the tip goes in `title`), for use inside a button or link. */
  plain?: boolean;
  /** Counted from the run's own `model_call` events; wins over the summary's mode (a live run can have a mock judge). */
  modes?: RunModes | null;
}) {
  const mode = modes?.mode ?? summaryMode;
  if (mode === "mixed" && modes) {
    const used = (["live", "mock", "replay"] as const).filter((k) => modes.counts[k]).map((k) => (k === "replay" ? "recorded" : k));
    const tip = `${recorded ? "A stored run played back from its log. " : ""}Its model answers came from more than one mode: ${runModesText(modes)}. Mock answers are not model output.`;
    const chip = (
      <Badge tone="mock" {...(plain ? { title: tip } : { tabIndex: 0, className: "cursor-help" })}>
        {recorded ? <History aria-hidden /> : <Bot aria-hidden />}
        {recorded ? `Recorded run · ${used.join(" + ")} models` : `${used.join(" + ")} models`}
      </Badge>
    );
    return plain ? chip : <Tooltip content={tip}>{chip}</Tooltip>;
  }
  if (!recorded && !finished) return <ModeBadge mode={mode} />;
  const models = MODELS[mode] ?? `${mode} models`;
  const tip = recorded
    ? mode === "live"
      ? "A run made earlier with real model calls, played back from its log. No model is called now."
      : mode === "mock"
        ? "A run made earlier with deterministic mocks (no API key), played back from its log. Not model output."
        : "A stored run played back from its log. Nothing is recomputed."
    : mode === "live"
      ? "This run used real model calls when it ran."
      : mode === "mock"
        ? "This run used deterministic mocks (no API key). Not model output."
        : `This run's provider mode was ${mode}.`;
  const chip = (
    <Badge tone={recorded || mode !== "live" ? "mock" : "outline"} {...(plain ? { title: tip } : { tabIndex: 0, className: "cursor-help" })}>
      {recorded ? <History aria-hidden /> : mode === "live" ? <Sparkles aria-hidden /> : <Bot aria-hidden />}
      {recorded ? `Recorded run · ${models}` : models}
    </Badge>
  );
  return plain ? chip : <Tooltip content={tip}>{chip}</Tooltip>;
}

/** Footnote marker for a cited value: hover/focus shows title and quote; the marker links to the source. */
export function CitationMark({ citation, n = 1 }: { citation: Citation; n?: number }) {
  let host = citation.url;
  try {
    host = new URL(citation.url).host;
  } catch {
    /* keep raw */
  }
  return (
    <Tooltip
      content={
        <span className="block space-y-1">
          <span className="block font-medium">{citation.title || host}</span>
          {citation.quote ? <span className="block italic opacity-90">“{citation.quote}”</span> : null}
          <span className="block font-mono text-[11px] opacity-80">{host}</span>
        </span>
      }
    >
      <a
        href={citation.url}
        target="_blank"
        rel="noreferrer noopener"
        aria-label={`Source ${n}: ${citation.title || host}`}
        className="align-super font-mono text-[10px] font-medium text-info underline-offset-2 hover:underline"
      >
        [{n}]
      </a>
    </Tooltip>
  );
}
