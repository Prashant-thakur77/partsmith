/** Shared agent documentation (used by /agents, /llms.txt and /prompt.txt). Mirrors docs/API.md. */

export const AGENT_RULES = [
  "Search the registry before building anything; prefer a verified part.",
  "Never rescale a part to force a fit — change the knob that controls the fitting dimension.",
  "If no part matches, say so plainly and call report_need (POST /api/v1/needs). Do not substitute an unrelated part.",
  "Report which dimensions were measured, which the user stated and which were inferred.",
  "Only the verifier sets `verified`. Quote max_error_mm from verification, never estimate it.",
  "Lengths are millimetres everywhere; angles are degrees.",
  "Results produced in mock or replay mode, or from synthetic inputs, must be labelled as such when you report them.",
];

export const MCP_TOOLS: { name: string; desc: string; writes?: boolean }[] = [
  { name: "search_parts", desc: "Search verified parts by words, family or size." },
  { name: "get_part", desc: "Full record: knobs with ranges, verification, facts, provenance." },
  { name: "get_variant", desc: "Plain words → knob values, with applied / not applied and a confidence." },
  { name: "bake", desc: "Bake a part with knob values to STL, 3MF, STEP, GLB or source. Cached by content." },
  { name: "find_matching", desc: "Parts that share a family or a mating interface." },
  { name: "list_families", desc: "Families with counts of parts and verified parts." },
  { name: "measure_photo", desc: "Photo on a mat → capture report and measurements in mm." },
  { name: "start_fix_job", desc: "Start a photo-to-part job.", writes: true },
  { name: "get_job", desc: "Job state, events, verification and artifacts." },
  { name: "report_need", desc: "Record a part nobody has built yet.", writes: true },
];

export const REST_GROUPS: { title: string; rows: [string, string, string][] }[] = [
  {
    title: "Registry",
    rows: [
      ["GET", "/parts?q=&family=&verified=&sort=&cursor=&limit=", "Search parts → {items, next_cursor, total}"],
      ["GET", "/parts/{slug}", "Part record + artifacts + lineage"],
      ["GET", "/parts/{slug}/params", "Typed knobs"],
      ["GET", "/parts/{slug}/bake?<knob>=<v>&format=stl|3mf|step|glb|view|py", "Bake result (or the file with &download=1)"],
      ["GET", "/parts/{slug}/variant?want=<plain words>", "Knob values with applied / not applied / confidence"],
      ["GET", "/parts/{slug}/matching", "Matching parts"],
      ["GET", "/parts/{slug}/template.pdf?<knobs>", "1:1 paper template"],
      ["GET", "/families", "Families with counts"],
      ["POST", "/needs", "Request a missing part {query}"],
      ["GET", "/stats", "Registry counters computed from the database"],
    ],
  },
  {
    title: "Jobs",
    rows: [
      ["POST", "/jobs/fix", "multipart: top, side?, mating?, intent, mat_kind, thickness_mm?, family_hint?"],
      ["GET", "/jobs/{id}", "Summary, events, partspec, measurements, verification, code, knobs, artifacts"],
      ["GET", "/jobs/{id}/events", "Server-sent events; replays history, then live; ?from_seq= resumes"],
      ["POST", "/jobs/{id}/answer", "Answer a paused question {id, value, via}"],
      ["POST", "/jobs/{id}/edit", "Text or voice edit → knob changes + bake"],
      ["GET", "/jobs/{id}/fit-outline?mat_id=", "Model outline in the mat frame for the screen fit check"],
      ["POST", "/jobs/{id}/fit-check", "multipart photo, mat_id → pass/fail with numbers"],
    ],
  },
  {
    title: "Measure, verify, system",
    rows: [
      ["POST", "/measure", "Photo → capture report + measurements (mm)"],
      ["POST", "/verify", "Part + knobs + measurements → verification"],
      ["GET", "/mats", "Mat layouts (marker bits included)"],
      ["GET", "/status", "Provider modes, keys present, cost"],
      ["GET", "/openapi.json", "OpenAPI 3.1"],
    ],
  },
];
