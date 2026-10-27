import { CheckCircle2, XCircle } from "lucide-react";
import type { FeatureResidual } from "@/lib/api-types";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Feature residuals from the verifier, worst |Δ| first. */
export function ResidualTable({ residuals, className }: { residuals: FeatureResidual[]; className?: string }) {
  const rows = [...residuals].sort((a, b) => Math.abs(b.delta_mm) - Math.abs(a.delta_mm));
  if (!rows.length) return <p className="py-6 text-center text-[13px] text-muted">No feature residuals yet — they appear after the first verify.</p>;
  return (
    <div tabIndex={0} role="region" aria-label="Feature residuals" className={cn("scrollbar-thin overflow-x-auto", className)}>
      <table className="w-full min-w-[420px] text-[12px]">
        <caption className="sr-only">Feature residuals: measured from the photo versus the model, sorted by absolute difference</caption>
        <thead>
          <tr className="border-b border-border text-left text-[11px] text-subtle">
            <th scope="col" className="py-2 pr-2 font-medium">Feature</th>
            <th scope="col" className="py-2 pr-2 text-right font-medium">Measured</th>
            <th scope="col" className="py-2 pr-2 text-right font-medium">Model</th>
            <th scope="col" className="py-2 pr-2 text-right font-medium">Δ</th>
            <th scope="col" className="py-2 pr-2 text-right font-medium">Tol</th>
            <th scope="col" className="py-2 text-right font-medium">Pass</th>
          </tr>
        </thead>
        <tbody className="font-mono tnum">
          {rows.map((r) => (
            <tr key={`${r.feature_id}.${r.quantity}`} className="border-b border-border last:border-0">
              <th scope="row" className="py-2 pr-2 text-left font-sans font-normal">
                <span className="text-fg">{r.feature_id}</span> <span className="text-subtle">{r.quantity.replace(/_/g, " ")}</span>
              </th>
              <td className="py-2 pr-2 text-right">{fmtNum(r.measured_mm)}</td>
              <td className="py-2 pr-2 text-right">{fmtNum(r.model_mm)}</td>
              <td className={cn("py-2 pr-2 text-right", !r.passed && "font-medium text-bad")}>
                {r.delta_mm > 0 ? "+" : r.delta_mm < 0 ? "−" : ""}
                {fmtNum(Math.abs(r.delta_mm))}
              </td>
              <td className="py-2 pr-2 text-right text-muted">±{fmtNum(r.tol_mm)}</td>
              <td className="py-2 text-right">
                {r.passed ? (
                  <CheckCircle2 className="ml-auto size-4 text-ok" aria-label="pass" />
                ) : (
                  <XCircle className="ml-auto size-4 text-bad" aria-label="fail" />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[11px] text-subtle">All values in mm. Δ = model − measured.</p>
    </div>
  );
}
