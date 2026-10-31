"use client";

/**
 * Feature detection from the API's own OpenAPI document. New round-2 endpoints and form fields light up controls only when
 * the running backend actually has them — never a fake or a disabled-looking stub.
 */
import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { API_PREFIX } from "./api";

type OpenApi = { paths?: Record<string, Record<string, unknown>>; components?: { schemas?: Record<string, { properties?: Record<string, unknown> }> } };

export type Capabilities = {
  /** `has("get", "/parts/{slug}/card.png")` — path relative to /api/v1, with `{param}` placeholders. */
  has: (method: string, path: string) => boolean;
  /** Field names of a multipart/JSON request body (e.g. the form fields /jobs/fix accepts). */
  fields: (method: string, path: string) => Set<string>;
  ready: boolean;
};

function bodyFields(doc: OpenApi, op: Record<string, unknown> | undefined): Set<string> {
  const content = (op?.requestBody as { content?: Record<string, { schema?: { $ref?: string; properties?: Record<string, unknown> } }> } | undefined)?.content ?? {};
  const out = new Set<string>();
  for (const media of Object.values(content)) {
    let schema = media.schema;
    if (schema?.$ref) schema = doc.components?.schemas?.[schema.$ref.split("/").pop() ?? ""] as typeof schema;
    for (const k of Object.keys(schema?.properties ?? {})) out.add(k);
  }
  return out;
}

const noSubscribe = () => () => {};

export function useCapabilities(): Capabilities {
  const q = useQuery({
    queryKey: ["openapi"],
    queryFn: async () => {
      const res = await fetch(`${API_PREFIX}/openapi.json`);
      if (!res.ok) throw new Error(String(res.status));
      return (await res.json()) as OpenApi;
    },
    staleTime: 5 * 60_000,
    retry: false,
  });
  // Until this component has hydrated, answer like the server did (no capabilities): the OpenAPI document can land in the
  // query cache before a Suspense-delayed subtree hydrates, and lighting up controls then is a hydration mismatch (#418).
  const hydrated = React.useSyncExternalStore(noSubscribe, () => true, () => false);
  const doc = hydrated ? q.data : undefined;
  // Placeholder names do not matter (`/needs/{id}/vote` matches `/needs/{need_id}/vote`).
  const norm = (p: string) => p.replace(/\{[^}]*\}/g, "{}");
  const paths = React.useMemo(() => new Map(Object.entries(doc?.paths ?? {}).map(([k, v]) => [norm(k), v])), [doc]);
  const op = (method: string, path: string) => paths.get(norm(`${API_PREFIX}${path}`))?.[method.toLowerCase()] as Record<string, unknown> | undefined;
  return {
    ready: !!doc,
    has: (method, path) => !!op(method, path),
    fields: (method, path) => (doc ? bodyFields(doc, op(method, path)) : new Set()),
  };
}
