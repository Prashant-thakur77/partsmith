/** Server-side builders for /llms.txt and /prompt.txt. The registry section is fetched live from the API. */
import { FamilySchema, PartListSchema } from "./api-types";
import { AGENT_RULES, MCP_TOOLS, REST_GROUPS } from "./agent-docs";
import { mcpUrl } from "./snippets";

function apiBase(): string {
  return `${(process.env.API_URL ?? "http://localhost:8000").replace(/\/$/, "")}/api/v1`;
}

async function getJson(path: string): Promise<unknown> {
  const res = await fetch(`${apiBase()}${path}`, { next: { revalidate: 300 }, signal: AbortSignal.timeout(2000) });
  if (!res.ok) throw new Error(String(res.status));
  return res.json();
}

async function registrySection(origin: string): Promise<string> {
  try {
    const [fam, parts] = await Promise.all([getJson("/families"), getJson("/parts?verified=true&limit=50&sort=newest")]);
    const families = FamilySchema.array().parse(fam);
    const list = PartListSchema.parse(parts);
    const lines = ["## Families", ...families.map((f) => `- ${f.family}: ${f.title} (${f.verified} verified of ${f.count})`), "", "## Verified parts"];
    for (const p of list.items) {
      lines.push(`- [${p.title}](${origin}/parts/${p.slug}): family ${p.family}, ${p.params_count} knobs${p.max_error_mm != null ? `, max error ${p.max_error_mm.toFixed(2)} mm` : ""}${p.origin !== "real" ? ` (${p.origin})` : ""}`);
    }
    if (list.total > list.items.length) lines.push(`- … ${list.total - list.items.length} more: ${origin}/api/v1/parts`);
    return lines.join("\n");
  } catch {
    return "## Registry\nThe registry listing is unavailable right now (API offline). Query /api/v1/parts directly.";
  }
}

export async function llmsTxt(origin: string): Promise<string> {
  const rest = REST_GROUPS.map((g) => [`### ${g.title}`, ...g.rows.map(([m, p, d]) => `- ${m} ${origin}/api/v1${p} — ${d}`)].join("\n")).join("\n\n");
  return [
    "# PartSmith",
    "",
    "> Photos of a broken plastic part on a calibration mat become a measured, verified, parametric CadQuery part. An open registry of verified parts is available over REST and MCP. All lengths are millimetres. The model proposes; deterministic code decides `verified`.",
    "",
    `- Agent instructions: ${origin}/prompt.txt`,
    `- OpenAPI: ${origin}/api/v1/openapi.json`,
    `- MCP (streamable HTTP): ${mcpUrl(origin)}`,
    "",
    "## REST",
    rest,
    "",
    "## MCP tools",
    ...MCP_TOOLS.map((t) => `- ${t.name}${t.writes ? " (writes)" : ""}: ${t.desc}`),
    "",
    await registrySection(origin),
    "",
  ].join("\n");
}

export function promptTxt(origin: string): string {
  return [
    "You can get physical replacement parts from PartSmith, an open registry of verified parametric parts.",
    `API: ${origin}/api/v1 · MCP: ${mcpUrl(origin)} · reference: ${origin}/llms.txt`,
    "",
    "How to work:",
    "1. search_parts (GET /parts?q=...) with the user's words and any sizes in mm.",
    "2. get_part to read the knobs (name, unit, min, max, affects_fit) and the verification record.",
    "3. get_variant(want=\"<the user's requirement in plain words>\"). Read `applied` and `not_applied`; if confidence is not high, tell the user exactly what was applied.",
    "4. bake with the knob values and give the user the STL (and STEP/3MF if useful) URLs.",
    "",
    "Rules:",
    ...AGENT_RULES.map((r) => `- ${r}`),
    "",
  ].join("\n");
}
