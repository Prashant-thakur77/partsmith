"use client";

import { Lock, Ruler } from "lucide-react";
import * as React from "react";
import type { Verification } from "@/lib/api-types";
import { fmtNum } from "@/lib/format";
import { noteCouponDownload } from "@/lib/coupon-fit";
import { useT } from "@/lib/i18n";
import { shipState } from "@/lib/ship";

/** Why a part is not one-click exportable, in plain words, from the verifier's own record. */
export function gateReason(v: Verification | null | undefined, t: (k: string, vars?: Record<string, string | number>) => string): string {
  if (!v) return t("gate.noRecord");
  const err = v.max_error_mm;
  const lim = v.thresholds.hausdorff_mm;
  const failed = v.tests.filter((x) => !x.passed).length;
  const parts: string[] = [];
  if (err != null) parts.push(t("gate.offBy", { err: fmtNum(err), lim: fmtNum(lim) }));
  if (failed) parts.push(t("gate.testsFailed", { n: failed }));
  if (!parts.length && v.reasons[0]) parts.push(v.reasons[0]);
  return parts.join(" · ") || t("gate.notVerified");
}

export { shipState, type ShipState } from "@/lib/ship";

export function useExportGate(v: Verification | null | undefined) {
  const [ack, setAck] = React.useState(false);
  const state = shipState(v);
  return { state, locked: state !== "verified", blocked: state === "blocked", ack, setAck, open: state === "verified" || (state === "best_effort" && ack) };
}

/**
 * Export gate notice for best-effort / unverified parts: the reason, a fit-test coupon suggestion, and an explicit
 * "I understand, download anyway" acknowledgement. Verified parts never see this.
 */
export function ExportGateNotice({
  verification,
  couponUrl,
  ack,
  onAck,
}: {
  verification: Verification | null | undefined;
  couponUrl?: string;
  ack: boolean;
  onAck: (v: boolean) => void;
}) {
  const { t } = useT();
  const id = React.useId();
  const blocked = shipState(verification) === "blocked";
  return (
    <div className="space-y-2.5 rounded-lg border border-warn-border bg-warn-soft p-3 text-[13px]" role="note">
      <div className="flex items-start gap-2">
        <Lock className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
        <div className="space-y-0.5">
          <p className="font-medium text-fg">{blocked ? t("gate.blockedTitle") : t("gate.title")}</p>
          <p className="text-muted">{gateReason(verification, t)}</p>
        </div>
      </div>
      {couponUrl ? (
        <a href={couponUrl} download onClick={noteCouponDownload} className="flex items-center gap-2 rounded-md border border-border bg-surface px-2.5 py-1.5 text-[12.5px] hover:border-border-strong">
          <Ruler className="size-3.5 text-muted" aria-hidden />
          <span>
            <span className="font-medium">{t("gate.coupon")}</span> <span className="text-muted">{t("gate.couponWhy")}</span>
          </span>
        </a>
      ) : null}
      {blocked ? (
        <p className="text-muted">{t("gate.blocked")}</p>
      ) : (
        <label htmlFor={id} className="flex cursor-pointer items-start gap-2 text-[12.5px] text-fg">
          <input id={id} type="checkbox" checked={ack} onChange={(e) => onAck(e.target.checked)} className="mt-0.5 size-4 accent-[var(--accent)]" />
          {t("gate.ack")}
        </label>
      )}
    </div>
  );
}
