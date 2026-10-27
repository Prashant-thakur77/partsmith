import { BookOpen, Bot, FlaskConical, History, Ruler, ScanLine, Sparkles, UserRound, Wand2, Box } from "lucide-react";
import type { Citation, DataOrigin, ProviderMode, Source } from "@/lib/api-types";
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

export function OriginBadge({ origin, hideReal = false }: { origin: DataOrigin; hideReal?: boolean }) {
  if (hideReal && origin === "real") return null;
  const o = ORIGIN[origin];
  const Icon = o.icon;
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
