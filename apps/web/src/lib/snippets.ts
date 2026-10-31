/** Copy-paste snippets for people and agents. URLs are built from the current origin; nothing here is a measured number. */

export const MCP_PATH = process.env.NEXT_PUBLIC_MCP_URL ?? "";

export function mcpUrl(origin: string): string {
  return MCP_PATH || `${origin}/mcp`;
}

function q(params: Record<string, number>): string {
  return Object.entries(params)
    .map(([k, v]) => `${encodeURIComponent(k)}=${v}`)
    .join("&");
}

export function pythonSnippet(slug: string, params: Record<string, number>, origin: string): string {
  const knobs = Object.entries(params)
    .map(([k, v]) => `    "${k}": ${v},`)
    .join("\n");
  return `import requests

API = "${origin}/api/v1"
knobs = {
${knobs}
}
bake = requests.get(f"{API}/parts/${slug}/bake", params={**knobs, "format": "stl"}).json()
print(bake["artifacts"]["stl"])  # content-addressed URL
print(bake["facts"])             # bbox_mm, volume_mm3, mass_g_pla, ...`;
}

export function curlSnippet(slug: string, params: Record<string, number>, origin: string): string {
  const qs = q(params);
  return `# part record (knobs, verification, provenance)
curl "${origin}/api/v1/parts/${slug}"

# bake this variant and download the STL (-OJ keeps the server's name: partsmith-<slug>-<changed knobs>.stl)
curl -OJ "${origin}/api/v1/parts/${slug}/bake?${qs}${qs ? "&" : ""}format=stl&download=1"

# plain-words variant (the server clamps to the knob ranges)
curl "${origin}/api/v1/parts/${slug}/variant?want=2+mm+thicker"`;
}

export function mcpCallSnippet(slug: string, params: Record<string, number>): string {
  return JSON.stringify({ tool: "bake", arguments: { slug, params, format: "stl" } }, null, 2);
}

export function agentPrompt(slug: string, title: string, origin: string): string {
  return `I need the PartSmith part "${title}" (${slug}). Read ${origin}/prompt.txt first.
Use the get_variant tool with my requirements in plain words, report which knobs were applied and which were not,
never rescale the part to force a fit, and give me the STL and STEP links from bake.`;
}

export function mcpConfigs(origin: string): { id: string; label: string; path: string; code: string }[] {
  const url = mcpUrl(origin);
  return [
    {
      id: "claude",
      label: "Claude Code",
      path: "terminal",
      code: `claude mcp add --transport http partsmith ${url}`,
    },
    {
      id: "muse",
      label: "Muse Code",
      path: "~/.config/muse/settings.json",
      code: JSON.stringify({ mcp_servers: { partsmith: { type: "http", url } } }, null, 2),
    },
    {
      id: "cursor",
      label: "Cursor",
      path: ".cursor/mcp.json",
      code: JSON.stringify({ mcpServers: { partsmith: { url } } }, null, 2),
    },
    {
      id: "vscode",
      label: "VS Code",
      path: ".vscode/mcp.json",
      code: JSON.stringify({ servers: { partsmith: { type: "http", url } } }, null, 2),
    },
    {
      id: "stdio",
      label: "Local (stdio)",
      path: "any MCP client",
      code: JSON.stringify(
        { mcpServers: { partsmith: { command: "uv", args: ["run", "python", "-m", "services.mcp", "--stdio"], cwd: "/path/to/partsmith" } } },
        null,
        2,
      ),
    },
  ];
}

/** Copyable lines for a part's data documents (verification record and typed knobs as JSON). */
export function dataSnippet(slug: string, origin: string): string {
  return `# the stored verification record: max error, limit, per-view and per-feature numbers, verifier version
curl "${origin}/api/v1/parts/${slug}/verification.json"

# the knobs as a JSON-Schema document: type, unit, default, min, max, step
curl "${origin}/api/v1/parts/${slug}/params.json"`;
}
