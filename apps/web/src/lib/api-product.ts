/**
 * Product routes (docs/API.md "Playground", "Describe it", "Variants", "Print it"): a typed client. Schemas live in
 * api-types.ts; every response is validated, and pages feature-detect these routes through the OpenAPI capability list.
 */
import { z } from "zod/mini";
import { apiUrl, request } from "./api";
import { DescribeRecordSchema, PrintPlanResultSchema, PrintShopsSchema, TemplateBakeSchema, TemplateCardSchema, TemplateDetailSchema, VariantSavedSchema } from "./api-types";

export type { CheckItem, DescribeQuestion, DescribeRecord, DescribeValue, NumberChecks, PrintPlan, PrintPlanResult, PrintShops, TemplateBake, TemplateCard, TemplateDetail, TemplatePreset, VariantSaved } from "./api-types";

/** The paths the pages look for in the OpenAPI document before showing a feature. */
export const PRODUCT = {
  templates: "/templates",
  templateBake: "/templates/{name}/bake",
  describe: "/describe",
  variants: "/parts/{slug}/variants",
  jobPrintPlan: "/jobs/{id}/print-plan",
  partPrintPlan: "/parts/{slug}/print-plan",
  printShops: "/print-shops",
} as const;

const json = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const enc = encodeURIComponent;

export const productApi = {
  templates: () => request(z.array(TemplateCardSchema), "/templates"),
  template: (name: string) => request(TemplateDetailSchema, `/templates/${enc(name)}`),
  templateBake: (name: string, params: Record<string, number>, signal?: AbortSignal) =>
    request(TemplateBakeSchema, `/templates/${enc(name)}/bake`, { query: { ...params, format: "view" }, signal }),
  /** Printable files from a template are not checked against a real part: the link carries `ack=1` (the page shows why first). */
  templateDownloadUrl: (name: string, params: Record<string, number>, format: "stl" | "3mf" | "step" | "py") =>
    apiUrl(`/templates/${enc(name)}/bake`, { ...params, format, download: 1, ack: format === "py" ? undefined : 1 }),
  templateCouponUrl: (name: string, params: Record<string, number>) => apiUrl(`/templates/${enc(name)}/coupon.stl`, params),
  describe: (text: string) => request(DescribeRecordSchema, "/describe", json({ text })),
  describeGet: (id: string) => request(DescribeRecordSchema, `/describe/${enc(id)}`),
  describeAnswer: (id: string, answers: Record<string, number | null>) => request(DescribeRecordSchema, `/describe/${enc(id)}/answers`, json({ answers })),
  saveVariant: (slug: string, params: Record<string, number>, title?: string) =>
    request(VariantSavedSchema, `/parts/${enc(slug)}/variants`, json({ params, ...(title ? { title } : {}) })),
  jobPrintPlan: (id: string) => request(PrintPlanResultSchema, `/jobs/${enc(id)}/print-plan`),
  partPrintPlan: (slug: string, params: Record<string, number>) => request(PrintPlanResultSchema, `/parts/${enc(slug)}/print-plan`, { query: params }),
  printShops: (city: string, title: string) => request(PrintShopsSchema, "/print-shops", json({ city, title })),
};
