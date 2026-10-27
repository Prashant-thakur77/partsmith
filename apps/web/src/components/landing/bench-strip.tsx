"use client";

import { useQuery } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import { BenchView } from "./bench-view";

/** Client fallback when the server could not fetch the bench report. */
export function BenchStrip() {
  const q = useQuery({ queryKey: ["bench"], queryFn: api.bench, retry: false });
  const state = q.isPending ? "pending" : q.isError ? (q.error instanceof ApiError && q.error.status === 404 ? "missing" : "error") : "ok";
  return <BenchView report={q.data} state={state} />;
}
