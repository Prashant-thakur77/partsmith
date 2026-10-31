/**
 * Open-data routes (docs/API.md "Search coverage and demand", "Part data as JSON"): search coverage on `/parts`,
 * `GET /demand`, and a part's verification record and knobs as JSON documents. Every response is validated; pages
 * feature-detect the routes through the OpenAPI capability list.
 */
import { z } from "zod/mini";
import { apiUrl, request, type PartsQuery } from "./api";
import { NeedSchema, PartCardSchema } from "./api-types";

const num = z.number();

export const EXTRAS = {
  demand: "/demand",
  verificationJson: "/parts/{slug}/verification.json",
  paramsJson: "/parts/{slug}/params.json",
} as const;

/** good | partial | none for a query; "all" when there is no query to match. */
export const SearchMatchSchema = z.enum(["good", "partial", "none", "all"]);
export type SearchMatch = z.output<typeof SearchMatchSchema>;

export const CoveredPartCardSchema = z.extend(PartCardSchema, {
  /** Share (0–1) of the query's words and numbers this part matches; absent without a query. */
  coverage: z.nullish(num),
});

export const CoveredPartListSchema = z.object({
  items: z.array(CoveredPartCardSchema),
  next_cursor: z.nullable(z.string()),
  total: z.int(),
  /** Best coverage over every candidate (null without a query; absent on an older backend). */
  coverage: z.nullish(num),
  match: z.nullish(SearchMatchSchema),
  hint: z.nullish(z.string()),
});
export type CoveredPartList = z.output<typeof CoveredPartListSchema>;

export const MissedSearchSchema = z.object({
  q: z.string(),
  count: z.int(),
  best_coverage: num,
  last_at: z.string(),
});
export type MissedSearch = z.output<typeof MissedSearchSchema>;

export const DemandSchema = z.object({
  needs: z.array(NeedSchema),
  missed_searches: z.array(MissedSearchSchema),
  miss_below: z._default(num, 0.5),
});
export type Demand = z.output<typeof DemandSchema>;

const enc = encodeURIComponent;

export const extrasApi = {
  /** Same query as `api.parts`, but keeps the coverage fields (an older backend simply leaves them out). */
  parts: (q: PartsQuery = {}) =>
    request(CoveredPartListSchema, "/parts", {
      query: {
        q: q.q,
        family: q.family,
        verified: q.verified ? "true" : undefined,
        sort: q.sort,
        cursor: q.cursor ?? undefined,
        limit: q.limit,
      },
    }),
  demand: () => request(DemandSchema, "/demand"),
  verificationJsonPath: (slug: string) => `/parts/${enc(slug)}/verification.json`,
  paramsJsonPath: (slug: string) => `/parts/${enc(slug)}/params.json`,
  verificationJsonUrl: (slug: string) => apiUrl(`/parts/${enc(slug)}/verification.json`),
  paramsJsonUrl: (slug: string) => apiUrl(`/parts/${enc(slug)}/params.json`),
};
