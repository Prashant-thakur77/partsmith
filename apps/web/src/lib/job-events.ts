/**
 * Live job events over SSE (`/jobs/{id}/events`). The server replays past events first, then streams live ones and ends
 * after `done`. We de-duplicate by `seq`, resume with `from_seq` after a dropped connection, and derive the workspace
 * view-model with `summarizeEvents` (pure, unit-testable).
 */
"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import { api } from "./api";
import {
  EventSchema,
  type ArtifactEvent,
  type DoneEvent,
  type IterationEvent,
  type JobEvent,
  type MetricEvent,
  type ModelCallEvent,
  type QuestionEvent,
  type StageEvent,
  type StageName,
} from "./api-types";

type State = { events: JobEvent[]; seen: Set<number> };
type Action = { type: "add"; events: JobEvent[] } | { type: "reset" };

function reducer(state: State, action: Action): State {
  if (action.type === "reset") return { events: [], seen: new Set() };
  const fresh = action.events.filter((e) => !state.seen.has(e.seq));
  if (fresh.length === 0) return state;
  const seen = new Set(state.seen);
  for (const e of fresh) seen.add(e.seq);
  const events = [...state.events, ...fresh].sort((a, b) => a.seq - b.seq);
  return { events, seen };
}

export type StreamState = "connecting" | "live" | "reconnecting" | "closed" | "error";

export function useJobEvents(jobId: string | null, initial: JobEvent[] = []) {
  const [state, dispatch] = useReducer(reducer, { events: [], seen: new Set<number>() });
  const [stream, setStream] = useState<StreamState>("connecting");
  const [contractErrors, setContractErrors] = useState<string[]>([]);
  const lastSeq = useRef(-1);
  const initialRef = useRef(initial);

  useEffect(() => {
    if (initialRef.current.length) dispatch({ type: "add", events: initialRef.current });
  }, []);

  useEffect(() => {
    lastSeq.current = Math.max(lastSeq.current, ...state.events.map((e) => e.seq));
  }, [state.events]);

  useEffect(() => {
    if (!jobId) return;
    let es: EventSource | null = null;
    let closed = false;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const open = () => {
      if (closed) return;
      const from = lastSeq.current >= 0 ? lastSeq.current + 1 : undefined;
      es = new EventSource(api.jobEventsUrl(jobId, from));
      setStream(retry === 0 ? "connecting" : "reconnecting");
      es.onopen = () => {
        retry = 0;
        setStream("live");
      };
      es.onmessage = (msg: MessageEvent<string>) => {
        let raw: unknown;
        try {
          raw = JSON.parse(msg.data);
        } catch {
          return;
        }
        const parsed = EventSchema.safeParse(raw);
        if (!parsed.success) {
          // Never swallow a contract mismatch: surface it in the workspace and the console.
          const issue = parsed.error.issues.slice(0, 2).map((i) => `${i.path.join(".")}: ${i.message}`).join("; ");
          const t = typeof raw === "object" && raw && "t" in raw ? String((raw as { t: unknown }).t) : "?";
          const msg = `event ${t}: ${issue}`;
          console.error(`[partsmith] SSE ${msg}`);
          setContractErrors((cur) => (cur.length > 20 ? cur : [...cur, msg]));
          return;
        }
        const ev = parsed.data;
        lastSeq.current = Math.max(lastSeq.current, ev.seq);
        dispatch({ type: "add", events: [ev] });
        if (ev.t === "done") {
          closed = true;
          es?.close();
          setStream("closed");
        }
      };
      es.onerror = () => {
        es?.close();
        if (closed) return;
        retry += 1;
        if (retry > 6) {
          setStream("error");
          return;
        }
        setStream("reconnecting");
        timer = setTimeout(open, Math.min(8000, 500 * 2 ** retry));
      };
    };
    open();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      es?.close();
    };
  }, [jobId]);

  return { events: state.events, stream, contractErrors };
}

export type StageState = { stage: StageName; status: StageEvent["status"] | "pending"; label: string; ms: number | null; iter: number | null };

export const STAGE_ORDER: StageName[] = [
  "capture",
  "measure",
  "understand",
  "ask",
  "plan",
  "build",
  "execute",
  "verify",
  "fix",
  "judge",
  "package",
  "learn",
];

export const STAGE_LABELS: Record<StageName, string> = {
  capture: "Check the photos",
  measure: "Measure in millimetres",
  understand: "Understand the part",
  ask: "Ask about hidden sizes",
  plan: "Plan the CAD",
  build: "Write the CAD program",
  execute: "Run it in the sandbox",
  verify: "Compare model to photo",
  fix: "Fix the differences",
  judge: "Independent review",
  package: "Package files",
  learn: "Record lessons",
};

export type EventSummary = {
  stages: StageState[];
  current: StageState | null;
  modelCalls: ModelCallEvent[];
  iterations: IterationEvent[];
  metrics: MetricEvent[];
  artifacts: Record<string, ArtifactEvent>;
  artifactsByIter: Record<number, Record<string, ArtifactEvent>>;
  question: QuestionEvent | null;
  done: DoneEvent | null;
  usd: number;
  tokens: number;
  logs: Extract<JobEvent, { t: "log" }>[];
  convergence: { iter: number; hausdorff_mm: number | null; iou: number | null }[];
};

export function summarizeEvents(events: JobEvent[]): EventSummary {
  const stageMap = new Map<StageName, StageState>();
  const modelCalls: ModelCallEvent[] = [];
  const iterations: IterationEvent[] = [];
  const metrics: MetricEvent[] = [];
  const artifacts: Record<string, ArtifactEvent> = {};
  const artifactsByIter: Record<number, Record<string, ArtifactEvent>> = {};
  const logs: EventSummary["logs"] = [];
  const answered = new Set<string>();
  let question: QuestionEvent | null = null;
  let done: DoneEvent | null = null;
  let current: StageState | null = null;

  for (const e of events) {
    switch (e.t) {
      case "stage": {
        const s: StageState = { stage: e.stage, status: e.status, label: e.label, ms: e.ms ?? null, iter: e.iter ?? null };
        stageMap.set(e.stage, s);
        current = s;
        break;
      }
      case "model_call":
        modelCalls.push(e);
        break;
      case "iteration":
        iterations.push(e);
        break;
      case "metric":
        metrics.push(e);
        break;
      case "artifact":
        artifacts[e.kind] = e;
        if (e.iter != null) (artifactsByIter[e.iter] ??= {})[e.kind] = e;
        break;
      case "question":
        question = e;
        break;
      case "answer":
        answered.add(e.id);
        break;
      case "log":
        logs.push(e);
        break;
      case "done":
        done = e;
        break;
    }
  }
  if (question && answered.has((question as QuestionEvent).id)) question = null;
  if (done) question = null;

  const stages = STAGE_ORDER.map(
    (stage) => stageMap.get(stage) ?? { stage, status: "pending" as const, label: "", ms: null, iter: null },
  );

  const byIter = new Map<number, { iter: number; hausdorff_mm: number | null; iou: number | null }>();
  for (const it of iterations) byIter.set(it.iter, { iter: it.iter, hausdorff_mm: it.hausdorff_mm ?? null, iou: it.iou ?? null });
  for (const m of metrics) {
    const row = byIter.get(m.iter) ?? { iter: m.iter, hausdorff_mm: null, iou: null };
    if (m.name === "hausdorff_mm" || m.name === "hausdorff") row.hausdorff_mm = m.value;
    if (m.name === "iou") row.iou = m.value;
    byIter.set(m.iter, row);
  }
  const convergence = [...byIter.values()].sort((a, b) => a.iter - b.iter);

  return {
    stages,
    current,
    modelCalls,
    iterations,
    metrics,
    artifacts,
    artifactsByIter,
    question,
    done,
    usd: modelCalls.reduce((a, m) => a + m.usd, 0),
    tokens: modelCalls.reduce((a, m) => a + m.tokens_in + m.tokens_out, 0),
    logs,
    convergence,
  };
}
