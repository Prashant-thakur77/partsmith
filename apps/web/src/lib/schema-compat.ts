/**
 * Compile-time drift check: the Zod-validated API types (api-types.ts) must stay assignable to the TypeScript generated from
 * the Pydantic contracts (schemas.ts, `pnpm schemas`). If the Python schemas change, `pnpm typecheck` fails here.
 */
import type * as Z from "./api-types";
import type * as G from "./schemas";

type Assert<T extends true> = T;
type Assignable<A, B> = [A] extends [B] ? true : false;

export type SchemaCompat = [
  Assert<Assignable<Z.Verification, G.Verification>>,
  Assert<Assignable<Z.ParamSpec, G.ParamSpec>>,
  Assert<Assignable<Z.FeatureResidual, G.FeatureResidual>>,
  Assert<Assignable<Z.ViewMetrics, G.ViewMetrics>>,
  Assert<Assignable<Z.JobSummary, G.JobSummary>>,
  Assert<Assignable<Z.BakeResult, G.BakeResult>>,
  Assert<Assignable<Z.PartFacts, G.PartFacts>>,
  Assert<Assignable<Z.VariantResult, G.VariantResult>>,
  Assert<Assignable<Z.Need, G.Need>>,
  Assert<Assignable<Z.Provenance, G.Provenance>>,
  Assert<Assignable<Z.CaptureReport, G.CaptureReport>>,
  Assert<Assignable<Z.ModelCallEvent, G.ModelCallEvent>>,
  Assert<Assignable<Z.IterationEvent, G.IterationEvent>>,
  Assert<Assignable<Z.StageEvent, G.StageEvent>>,
  Assert<Assignable<Z.QuestionEvent, G.QuestionEvent>>,
  Assert<Assignable<Z.DoneEvent, G.DoneEvent>>,
  Assert<Assignable<Z.Measurements, G.Measurements>>,
  Assert<Assignable<Z.ThoughtEvent, G.ThoughtEvent>>,
  Assert<Assignable<Z.ToolCallEvent, G.ToolCallEvent>>,
  Assert<Assignable<Z.FocusEvent, G.FocusEvent>>,
  Assert<Assignable<Z.UncheckedValue, G.UncheckedValue>>,
  Assert<Assignable<Z.CitedOffer, G.CitedOffer>>,
  Assert<Assignable<Z.CitedPlace, G.CitedPlace>>,
  Assert<Assignable<Z.OemPart, G.OemPart>>,
  // `overlay_url` is optional in the web schema (nullish) and a defaulted string in Pydantic; everything else must match.
  Assert<Assignable<Omit<Z.FitCheckResult, "overlay_url">, Omit<G.FitCheckResult, "overlay_url">>>,
];
