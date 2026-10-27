import { cn } from "@/lib/utils";

const tones = {
  ok: "bg-ok",
  warn: "bg-warn",
  bad: "bg-bad",
  idle: "bg-subtle",
  live: "bg-accent",
  info: "bg-info",
} as const;

export function StatusDot({ tone = "idle", pulse = false, className }: { tone?: keyof typeof tones; pulse?: boolean; className?: string }) {
  return (
    <span aria-hidden className={cn("relative inline-flex size-2 shrink-0 rounded-full", tones[tone], pulse && "animate-pulse-dot", className)} />
  );
}
