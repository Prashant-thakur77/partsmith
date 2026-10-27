"use client";

import { ArrowRight, Bot, FileText, Plug } from "lucide-react";
import Link from "next/link";
import { useOrigin } from "@/lib/use-origin";
import { CodeBlock } from "../ui/code-block";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";

export function AgentsStrip() {
  const origin = useOrigin();
  return (
    <div className="grid gap-6 rounded-xl border border-border bg-surface p-5 sm:p-6 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
      <div className="space-y-4">
        <div className="inline-flex size-9 items-center justify-center rounded-lg border border-border bg-surface-2">
          <Bot className="size-4" aria-hidden />
        </div>
        <h3 className="text-xl font-semibold tracking-tight">Built for coding agents too</h3>
        <p className="text-[14px] leading-6 text-muted">
          Every verified part is a program with typed knobs. Agents search, ask for a variant in plain words, and bake an STL — over
          REST or MCP. The rules are simple: never rescale a part to force a fit, change the right knob; if nothing matches, say so and
          report the need.
        </p>
        <ul className="space-y-2 text-[13px]">
          <li className="flex items-center gap-2">
            <Plug className="size-4 text-muted" aria-hidden /> MCP tools: search_parts, get_variant, bake, find_matching, report_need…
          </li>
          <li className="flex items-center gap-2">
            <FileText className="size-4 text-muted" aria-hidden />
            <a href="/llms.txt" className="font-mono text-accent-text hover:underline">/llms.txt</a> and{" "}
            <a href="/prompt.txt" className="font-mono text-accent-text hover:underline">/prompt.txt</a>
          </li>
        </ul>
        <Link href="/agents" className="inline-flex items-center gap-1 text-[13px] font-medium text-accent-text hover:underline">
          Agent setup guide <ArrowRight className="size-3.5" aria-hidden />
        </Link>
      </div>
      <Tabs defaultValue="rest" className="min-w-0">
        <TabsList>
          <TabsTrigger value="rest">REST</TabsTrigger>
          <TabsTrigger value="mcp">MCP</TabsTrigger>
          <TabsTrigger value="prompt">Agent prompt</TabsTrigger>
        </TabsList>
        <TabsContent value="rest">
          <CodeBlock
            title="shell"
            wrap
            code={`# find a part, then bake a variant as STL\ncurl "${origin}/api/v1/parts?q=cable+clip&verified=true"\ncurl "${origin}/api/v1/parts/<slug>/variant?want=fits+a+6+mm+cable"\ncurl -o part.stl "${origin}/api/v1/parts/<slug>/bake?format=stl&download=1"`}
          />
        </TabsContent>
        <TabsContent value="mcp">
          <CodeBlock title="mcp config (JSON)" code={`{\n  "mcpServers": {\n    "partsmith": { "type": "http", "url": "${origin}/mcp" }\n  }\n}`} />
        </TabsContent>
        <TabsContent value="prompt">
          <CodeBlock
            title="paste into your agent"
            wrap
            code={`Use PartSmith for physical replacement parts. Read ${origin}/prompt.txt first. Search before you build, pick a verified part, change knobs instead of scaling, and tell me which dimensions were measured and which were assumed.`}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
