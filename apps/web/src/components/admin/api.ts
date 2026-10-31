/** Admin console calls. `request()` attaches the stored admin token; every response is validated with the Zod schemas. */
import { request } from "@/lib/api";
import {
  ADMIN_API,
  AdminOverviewSchema,
  AdminPartsSchema,
  AuditLogSchema,
  DemandSchema,
  ModerationResultSchema,
  TaughtRuleSchema,
  TaughtRulesSchema,
  path,
} from "@/lib/api-admin";

const post = (body: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const adminApi = {
  overview: () => request(AdminOverviewSchema, ADMIN_API.overview),
  audit: (q: { limit?: number; action?: string; target?: string } = {}) => request(AuditLogSchema, ADMIN_API.audit, { query: q }),
  parts: () => request(AdminPartsSchema, ADMIN_API.parts),
  moderate: (slug: string, action: "unpublish" | "republish", reason: string) =>
    request(ModerationResultSchema, path(action === "unpublish" ? ADMIN_API.unpublish : ADMIN_API.republish, "slug", slug), post({ reason })),
  rules: () => request(TaughtRulesSchema, ADMIN_API.rules),
  switchRule: (id: string, action: "disable" | "enable", reason: string) =>
    request(TaughtRuleSchema, path(action === "disable" ? ADMIN_API.disable : ADMIN_API.enable, "rule_id", id), post({ reason })),
  demand: () => request(DemandSchema, ADMIN_API.demand),
};

