import { cn } from "@/lib/utils";

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={cn("size-6", className)} aria-hidden>
      <rect x="1.5" y="1.5" width="21" height="21" rx="5" className="fill-inverse" />
      <path d="M6 17V7h7.5a3.5 3.5 0 0 1 0 7H9" fill="none" strokeWidth="2.2" strokeLinecap="square" className="stroke-inverse-fg" />
      <circle cx="16.6" cy="17" r="1.9" className="fill-accent" />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <LogoMark />
      <span className="text-[15px] font-semibold tracking-[-0.02em] text-fg">PartSmith</span>
    </span>
  );
}
