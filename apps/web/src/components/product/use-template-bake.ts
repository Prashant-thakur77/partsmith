"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { productApi } from "@/lib/api-product";
import { useDebounced } from "@/lib/hooks";

/** Re-bake a template whenever the knob values settle (debounced, cached server-side and here). */
export function useTemplateBake(name: string | null | undefined, values: Record<string, number> | null, debounceMs = 220) {
  const debounced = useDebounced(values, debounceMs);
  const params = debounced ? Object.fromEntries(Object.entries(debounced).sort(([a], [b]) => a.localeCompare(b))) : null;
  const q = useQuery({
    queryKey: ["template-bake", name, params],
    queryFn: ({ signal }) => productApi.templateBake(name!, params!, signal),
    enabled: !!name && !!params,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    retry: false,
  });
  return { ...q, pending: values !== debounced || q.isFetching };
}
