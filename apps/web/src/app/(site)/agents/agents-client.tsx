"use client";

import { FileText, PenLine } from "lucide-react";
import { Container, PageHeader, Section } from "@/components/layout/page";
import { Badge } from "@/components/ui/badge";
import { CodeBlock } from "@/components/ui/code-block";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AGENT_RULES, MCP_TOOLS, REST_GROUPS } from "@/lib/agent-docs";
import { mcpConfigs, mcpUrl } from "@/lib/snippets";
import { useOrigin } from "@/lib/use-origin";

export function AgentsClient() {
  const origin = useOrigin();
  const configs = mcpConfigs(origin);
  return (
    <>
      <PageHeader
        eyebrow="For agents"
        title="Physical parts for coding agents"
        description="Search verified parts, turn plain words into knob values, and bake STL or STEP — over REST or MCP. Browsing needs no key."
      />
      <Container className="space-y-16 py-10">
        <div className="grid gap-3 md:grid-cols-3">
          {[
            { href: "/llms.txt", title: "llms.txt", body: "Reference for language models: endpoints, tools, families." },
            { href: "/prompt.txt", title: "prompt.txt", body: "Working instructions to paste into an agent's system prompt." },
            { href: "/api/v1/openapi.json", title: "openapi.json", body: "The full REST contract, OpenAPI 3.1." },
          ].map((d) => (
            <a key={d.href} href={d.href} className="group space-y-1.5 rounded-lg border border-border bg-surface p-4 hover:border-border-strong">
              <div className="flex items-center gap-2 font-mono text-[13px] font-medium text-fg group-hover:text-accent-text">
                <FileText className="size-4 text-muted" aria-hidden /> {d.title}
              </div>
              <p className="text-[13px] text-muted">{d.body}</p>
            </a>
          ))}
        </div>

        <Section id="mcp" title="Connect over MCP" description={`Streamable HTTP endpoint: ${mcpUrl(origin)}. Read-only tools need no key; tools that write are marked.`}>
          <Tabs defaultValue={configs[0]!.id}>
            <TabsList>
              {configs.map((c) => (
                <TabsTrigger key={c.id} value={c.id}>
                  {c.label}
                </TabsTrigger>
              ))}
            </TabsList>
            {configs.map((c) => (
              <TabsContent key={c.id} value={c.id}>
                <CodeBlock title={c.path} code={c.code} />
              </TabsContent>
            ))}
          </Tabs>
          <ul className="grid gap-2 sm:grid-cols-2">
            {MCP_TOOLS.map((t) => (
              <li key={t.name} className="flex items-start gap-3 rounded-md border border-border bg-surface px-3 py-2.5">
                <code className="shrink-0 font-mono text-[12.5px] text-fg">{t.name}</code>
                <span className="flex-1 text-[12.5px] text-muted">{t.desc}</span>
                {t.writes ? (
                  <Badge tone="warn">
                    <PenLine aria-hidden /> writes
                  </Badge>
                ) : null}
              </li>
            ))}
          </ul>
        </Section>

        <Section id="rest" title="REST" description={`Base URL ${origin}/api/v1. JSON in and out; all lengths in millimetres. Errors are {"error": {code, message, closest_matches?}}.`}>
          <div className="space-y-6">
            {REST_GROUPS.map((g) => (
              <div key={g.title} className="space-y-2">
                <h3 className="text-[13px] font-semibold">{g.title}</h3>
                <div tabIndex={0} role="region" aria-label={`${g.title} endpoints`} className="scrollbar-thin overflow-x-auto rounded-lg border border-border bg-surface">
                  <table className="w-full min-w-[640px] text-[12.5px]">
                    <tbody>
                      {g.rows.map(([m, path, desc]) => (
                        <tr key={m + path} className="border-b border-border last:border-0">
                          <td className="w-16 px-3 py-2 align-top">
                            <Badge tone={m === "GET" ? "neutral" : "accent"} className="font-mono">
                              {m}
                            </Badge>
                          </td>
                          <td className="px-3 py-2 align-top font-mono text-fg">{path}</td>
                          <td className="px-3 py-2 align-top text-muted">{desc}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
            <CodeBlock
              title="example"
              code={`curl "${origin}/api/v1/parts?q=cooler+wheel&verified=true"\ncurl "${origin}/api/v1/parts/<slug>/variant?want=32+mm+wheel,+8+mm+axle"\ncurl -o wheel.stl "${origin}/api/v1/parts/<slug>/bake?diameter=32&format=stl&download=1"`}
            />
          </div>
        </Section>

        <Section id="rules" title="Rules for agents" description="Also in prompt.txt.">
          <ol className="space-y-2">
            {AGENT_RULES.map((r, i) => (
              <li key={r} className="flex gap-3 rounded-md border border-border bg-surface px-4 py-3 text-[13.5px]">
                <span className="font-mono text-[12px] text-accent-text">{String(i + 1).padStart(2, "0")}</span>
                <span>{r}</span>
              </li>
            ))}
          </ol>
        </Section>
      </Container>
    </>
  );
}
