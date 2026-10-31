"use client";

import { Check, Copy } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";

export function CopyButton({ value, label = "Copy", className }: { value: string; label?: string; className?: string }) {
  const [copied, setCopied] = React.useState(false);
  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = value;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };
  return (
    <button
      type="button"
      onClick={onCopy}
      aria-label={copied ? "Copied" : label}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[12px] font-medium text-muted transition-[color,background-color,border-color,transform] duration-[var(--dur-hover)] ease-[var(--ease-out)] active:scale-[0.97] hover:bg-surface-3 hover:text-fg",
        className,
      )}
    >
      {copied ? <Check className="size-3.5 text-ok" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
      <span>{copied ? "Copied" : label}</span>
      <span className="sr-only" aria-live="polite">
        {copied ? "Copied to clipboard" : ""}
      </span>
    </button>
  );
}
