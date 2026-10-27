import { Bot, FlaskConical, History, Ruler, ScanLine, Sparkles, UserRound, Wand2, Box } from "lucide-react";
import type { DataOrigin, ProviderMode, Source } from "@/lib/api-types";
import { Badge } from "./badge";
import { Tooltip } from "./tooltip";

const SOURCE: Record<Source, { label: string; tip: string; icon: typeof Ruler; tone: "neutral" | "info" | "warn" }> = {
  measured: { label: "measured", tip: "Measured by code from the photo on the calibrated mat.", icon: Ruler, tone: "neutral" },
  user_stated: { label: "you said", tip: "A value you typed or said. Used as given.", icon: UserRound, tone: "info" },
  inferred: { label: "inferred", tip: "Not visible in the photo; proposed by the model and checked against the rest of the part.", icon: Wand2, tone: "warn" },
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
