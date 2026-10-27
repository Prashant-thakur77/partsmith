"use client";

import { useQuery } from "@tanstack/react-query";
import { Bot, History, Layers, PlugZap } from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useHealth } from "./api-health";

/** Site-wide honesty banner: shown whenever any provider runs as a mock or replay, or the API is unreachable. */
export function ModeBanner({ className, wide = false }: { className?: string; wide?: boolean }) {
  const health = useHealth();
  const status = useQuery({ queryKey: ["status"], queryFn: api.status, refetchInterval: 60_000, retry: false, enabled: !!health.data?.ok });

  if (health.isError) {
    return (
      <Bar wide={wide} className={className} icon={PlugZap} tone="offline">
        <strong className="font-semibold">API offline.</strong> Start the backend with{" "}
        <code className="rounded bg-surface-3 px-1 py-px font-mono text-[12px]">make dev</code> — pages show empty states, never
        invented data.
      </Bar>
    );
  }
  const s = status.data;
  if (!s || s.mode === "live") return null;
  const nonLive = s.providers.filter((p) => p.mode !== "live");
  if (s.mode === "mock") {
    return (
      <Bar wide={wide} className={className} icon={Bot} tone="mock">
        <strong className="font-semibold">Mock mode:</strong> no API keys — results are deterministic mocks, not model output.{" "}
        <Link href="/status" className="underline underline-offset-2 hover:text-fg">
          Provider status
        </Link>
      </Bar>
    );
  }
  if (s.mode === "replay") {
    return (
      <Bar wide={wide} className={className} icon={History} tone="mock">
        <strong className="font-semibold">Replay mode:</strong> model responses are recorded runs played back, not live calls.{" "}
        <Link href="/status" className="underline underline-offset-2 hover:text-fg">
          Provider status
        </Link>
      </Bar>
    );
  }
  return (
    <Bar wide={wide} className={className} icon={Layers} tone="mock">
      <strong className="font-semibold">Mixed mode:</strong> {nonLive.length} of {s.providers.length} stages run on mocks or replays (
      {nonLive.map((p) => p.stage).join(", ")}).{" "}
      <Link href="/status" className="underline underline-offset-2 hover:text-fg">
        See which
      </Link>
    </Bar>
  );
}

function Bar({
  children,
  icon: Icon,
  tone,
  className,
  wide,
}: {
  children: React.ReactNode;
  icon: typeof Bot;
  tone: "mock" | "offline";
  className?: string;
  wide?: boolean;
}) {
  return (
    <div
      role="status"
      className={cn(
        "border-b border-border text-[12.5px] leading-5 text-muted",
        tone === "mock" ? "bg-surface-2 bg-hatch" : "bg-surface-2",
        className,
      )}
    >
      <div className={cn("mx-auto flex items-start", wide ? "max-w-none" : "max-w-[1200px]", " gap-2 px-4 py-2 sm:items-center sm:px-6")}>
        <Icon className="mt-0.5 size-3.5 shrink-0 sm:mt-0" aria-hidden />
        <p className="min-w-0">{children}</p>
      </div>
    </div>
  );
}
