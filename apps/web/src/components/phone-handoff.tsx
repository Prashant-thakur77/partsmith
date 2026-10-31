"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Copy, Smartphone } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { isLocalOrigin } from "@/lib/page-groups";
import { useOrigin } from "@/lib/use-origin";
import { cn } from "@/lib/utils";
import { QrCode } from "./qr-code";
import { toast } from "./ui/toast";

/**
 * QR + link that opens `path` on the phone. Shown on laptops/tablets; hidden on phones (they already are the phone).
 * On a local-only origin the QR is replaced by a same-size note, so nothing moves when the real origin is known.
 */
export function PhoneHandoff({ path, className, compact = false, dark = false }: { path: string; className?: string; compact?: boolean; dark?: boolean }) {
  const { t } = useT();
  const origin = useOrigin();
  const url = `${origin}${path}`;
  const local = isLocalOrigin(origin);
  const size = compact ? 112 : 136;
  return (
    <div className={cn("hidden items-center gap-4 rounded-xl border p-4 md:flex", dark ? "border-white/15 bg-black/70 text-white" : "border-border bg-surface", className)}>
      {local ? (
        <p
          data-testid="phone-qr-local"
          style={{ width: size, height: size }}
          className={cn("flex shrink-0 items-center rounded-md border border-dashed p-2 text-[11px] leading-[14px]", dark ? "border-white/25 text-white/70" : "border-border-strong text-muted")}
        >
          {t("phone.local")}
        </p>
      ) : (
        <QrCode value={url} size={size} label={`QR code: ${url}`} />
      )}
      <div className="min-w-0 space-y-1.5">
        <p className="flex items-center gap-1.5 text-[14px] font-semibold">
          <Smartphone className="size-4" aria-hidden /> {t("phone.title")}
        </p>
        <p className={cn("text-[12.5px] leading-5", dark ? "text-white/70" : "text-muted")}>{t("phone.body")}</p>
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard?.writeText(url);
            toast(t("phone.copied"));
          }}
          className={cn("inline-flex max-w-full items-center gap-1.5 truncate font-mono text-[11.5px] underline-offset-2 hover:underline", dark ? "text-white/80" : "text-accent-text")}
        >
          <Copy className="size-3 shrink-0" aria-hidden /> <span className="truncate">{url.replace(/^https?:\/\//, "")}</span>
        </button>
      </div>
    </div>
  );
}

/**
 * Laptop side of the two-device flow on /fix: watches for a fix job created after this page opened (i.e. started on the
 * phone) and offers to open its workspace. Polls only while the tab is visible.
 */
export function PhoneJobWatcher() {
  const { t } = useT();
  const [since] = React.useState(() => Date.now() / 1000);
  const q = useQuery({
    queryKey: ["jobs", "watch"],
    queryFn: () => api.jobs(3),
    refetchInterval: () => (document.visibilityState === "visible" ? 4000 : false),
    retry: false,
  });
  const job = q.data?.find((j) => j.kind === "fix" && j.created_at > since);
  if (!job) return null;
  return (
    <div role="status" className="flex flex-col gap-3 rounded-xl border border-accent bg-accent-soft p-4 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-[14px] font-medium text-fg">
        {t("phone.started")}: <span className="font-normal">{job.title || job.id}</span>
      </p>
      <Link href={`/jobs/${encodeURIComponent(job.id)}`} className="inline-flex h-9 items-center gap-1.5 rounded-md bg-accent px-4 text-sm font-medium text-accent-fg">
        {t("phone.open")} <ArrowRight className="size-4" aria-hidden />
      </Link>
    </div>
  );
}
