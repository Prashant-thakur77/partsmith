"use client";

import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { api } from "@/lib/api";
import type { PartRecord } from "@/lib/api-types";
import { useBake } from "@/lib/hooks";

/** Knob state + live re-bake for one registry part. Values start from the part's defaults (or `initial`, e.g. URL params). */
export function useLivePart(slug: string | null, initial?: Record<string, number>) {
  const part = useQuery({ queryKey: ["part", slug], queryFn: () => api.part(slug!), enabled: !!slug });
  const [values, setValues] = React.useState<Record<string, number> | null>(null);
  const seeded = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!part.data || seeded.current === part.data.slug) return;
    seeded.current = part.data.slug;
    setValues(seedValues(part.data, initial));
  }, [part.data, initial]);
  const changed = !!part.data && !!values && part.data.params.some((p) => values[p.name] !== part.data!.defaults[p.name]);
  const needBake = changed || (!!part.data && !part.data.artifacts.view);
  const bake = useBake(slug, needBake ? values : null);
  const viewUrl = needBake ? (bake.data?.artifacts.view ?? part.data?.artifacts.view) : part.data?.artifacts.view;
  return { part, values: values ?? {}, setValues, bake, viewUrl, changed };
}

function seedValues(p: PartRecord, initial?: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {};
  for (const spec of p.params) {
    const v = initial?.[spec.name];
    out[spec.name] = v !== undefined && Number.isFinite(v) ? Math.min(spec.max, Math.max(spec.min, v)) : (p.defaults[spec.name] ?? spec.default);
  }
  return out;
}
