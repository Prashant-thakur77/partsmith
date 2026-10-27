"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileDown, Plus, Store, UserPlus } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { AdminAccess, AdminLock, useAdmin } from "@/components/admin-access";
import { Container, PageHeader, Section } from "@/components/layout/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Input, Label, Select } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { adminToken } from "@/lib/admin";
import { API_PREFIX, api } from "@/lib/api";
import { R2, shop, type BatchRow } from "@/lib/api-r2";
import { useCapabilities } from "@/lib/capabilities";
import { fmtNum, timeAgo, titleCase } from "@/lib/format";

async function downloadSheet(id: string, name: string) {
  const token = adminToken();
  const res = await fetch(`${API_PREFIX}${shop.sheetPath(id)}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      msg = ((await res.json()) as { error?: { message?: string } }).error?.message ?? msg;
    } catch {
      /* not JSON */
    }
    throw new Error(`Job sheet: ${msg}`);
  }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = `${name.replace(/[^\w-]+/g, "-").toLowerCase() || "batch"}-job-sheet.pdf`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

function RowStatus({ r }: { r: BatchRow }) {
  if (r.status === "done") return r.verified ? <Badge tone="ok">Verified</Badge> : <Badge tone="warn">Best effort</Badge>;
  if (["failed", "cancelled"].includes(r.status)) return <Badge tone="bad">{titleCase(r.status)}</Badge>;
  if (r.status === "unknown") return <Badge tone="neutral">Unknown job</Badge>;
  return <Badge tone="accent">{titleCase(r.status.replaceAll("_", " "))}</Badge>;
}

function BatchView({ id }: { id: string }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["shop-batch", id], queryFn: () => shop.batch(id), refetchInterval: 10_000 });
  const recent = useQuery({ queryKey: ["jobs", "recent-fix"], queryFn: () => api.jobs(30) });
  const [customer, setCustomer] = React.useState("");
  const [contact, setContact] = React.useState("");
  const [jobId, setJobId] = React.useState("");
  const add = useMutation({
    mutationFn: () => shop.addJob(id, { customer: customer.trim(), job_id: jobId.trim(), contact: contact.trim() }),
    onSuccess: (b) => {
      qc.setQueryData(["shop-batch", id], b);
      void qc.invalidateQueries({ queryKey: ["shop-batches"] });
      setJobId("");
    },
  });
  const sheet = useMutation({ mutationFn: () => downloadSheet(id, q.data?.name ?? "batch") });
  if (q.isPending) return <Skeleton className="h-48" />;
  if (q.isError) return <ErrorState error={q.error} what="this batch" onRetry={() => void q.refetch()} />;
  const b = q.data;
  const fixJobs = (recent.data ?? []).filter((j) => j.kind === "fix" && !j.is_replay);
  const total = b.rows.reduce((acc, r) => acc + (r.price_inr ?? 0), 0);
  const priced = b.rows.some((r) => r.price_inr != null);
  return (
    <Section
      title={b.name}
      description={`${b.customers.length} customer${b.customers.length === 1 ? "" : "s"} · ${b.rows.length} job${b.rows.length === 1 ? "" : "s"}${b.created_at ? ` · started ${timeAgo(b.created_at)}` : ""}`}
      actions={
        <Button variant="solid" size="sm" onClick={() => sheet.mutate()} disabled={sheet.isPending || b.rows.length === 0}>
          {sheet.isPending ? <Spinner label="Preparing" /> : <FileDown aria-hidden />} Job sheet (PDF)
        </Button>
      }
    >
      {sheet.isError ? <ErrorState error={sheet.error} compact what="the job sheet" /> : null}
      <form
        className="grid grid-cols-1 gap-3 rounded-lg border border-border bg-surface p-4 md:grid-cols-[1fr_1fr_1.4fr_auto] md:items-end"
        onSubmit={(e) => {
          e.preventDefault();
          if (customer.trim() && jobId.trim()) add.mutate();
        }}
      >
        <div className="space-y-1.5">
          <Label htmlFor="cust-name">Customer</Label>
          <Input id="cust-name" value={customer} onChange={(e) => setCustomer(e.target.value)} placeholder="Name or token number" list="batch-customers" />
          <datalist id="batch-customers">
            {b.customers.map((c) => (
              <option key={c.name} value={c.name} />
            ))}
          </datalist>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="cust-contact">Contact (optional)</Label>
          <Input id="cust-contact" value={contact} onChange={(e) => setContact(e.target.value)} placeholder="Phone" inputMode="tel" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="cust-job">Fix job</Label>
          <Select id="cust-job" className="w-full" value={jobId} onChange={(e) => setJobId(e.target.value)}>
            <option value="">{fixJobs.length ? "Choose a recent fix…" : "No fix jobs yet"}</option>
            {fixJobs.map((j) => (
              <option key={j.id} value={j.id}>
                {j.title || j.id} · {j.status.replaceAll("_", " ")}
              </option>
            ))}
          </Select>
        </div>
        <Button type="submit" variant="outline" disabled={!customer.trim() || !jobId.trim() || add.isPending}>
          {add.isPending ? <Spinner label="Adding" /> : <UserPlus aria-hidden />} Add
        </Button>
        <p className="text-[12px] text-muted md:col-span-4">
          Start each customer&apos;s fix on{" "}
          <Link href="/fix" className="text-accent-text underline">
            Fix a part
          </Link>
          , then add the job here. Statuses refresh every 10 s.
        </p>
        {add.isError ? <ErrorState error={add.error} compact what="the job" className="md:col-span-4" /> : null}
      </form>
      {b.rows.length === 0 ? (
        <EmptyState compact icon={UserPlus} title="No jobs in this batch yet" />
      ) : (
        <div tabIndex={0} role="region" aria-label="Batch jobs" className="scrollbar-thin overflow-x-auto rounded-lg border border-border bg-surface">
          <table className="w-full min-w-[680px] text-[13px]">
            <thead className="bg-surface-2 text-left text-[11px] text-subtle">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Customer</th>
                <th scope="col" className="px-3 py-2 font-medium">Part</th>
                <th scope="col" className="px-3 py-2 font-medium">Status</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Max error</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">PLA</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Estimate</th>
              </tr>
            </thead>
            <tbody>
              {b.rows.map((r) => (
                <tr key={`${r.customer}-${r.job_id}`} className="border-t border-border">
                  <th scope="row" className="px-3 py-2 text-left font-medium">
                    {r.customer}
                    {r.contact ? <span className="block text-[11.5px] font-normal text-subtle">{r.contact}</span> : null}
                  </th>
                  <td className="px-3 py-2">
                    <Link href={`/jobs/${encodeURIComponent(r.job_id)}`} className="hover:underline">
                      {r.title || r.job_id}
                    </Link>
                  </td>
                  <td className="px-3 py-2">
                    <RowStatus r={r} />
                  </td>
                  <td className="px-3 py-2 text-right font-mono tnum">{r.max_error_mm != null ? `${fmtNum(r.max_error_mm)} mm` : "—"}</td>
                  <td className="px-3 py-2 text-right font-mono tnum">{r.grams_pla != null ? `${fmtNum(r.grams_pla, 1)} g` : "—"}</td>
                  <td className="px-3 py-2 text-right font-mono tnum">{r.price_inr != null ? `₹${fmtNum(r.price_inr, 0)}` : "—"}</td>
                </tr>
              ))}
            </tbody>
            {priced ? (
              <tfoot>
                <tr className="border-t border-border bg-surface-2 text-[12px]">
                  <td colSpan={5} className="px-3 py-2 text-muted">
                    Estimate = PLA grams × ₹{fmtNum(b.price?.inr_per_g_pla ?? 0, 2)}/g{b.price?.inr_base_per_part ? ` + ₹${fmtNum(b.price.inr_base_per_part, 0)} per part` : ""} (server rate)
                  </td>
                  <td className="px-3 py-2 text-right font-mono font-medium tnum">₹{fmtNum(total, 0)}</td>
                </tr>
              </tfoot>
            ) : null}
          </table>
        </div>
      )}
    </Section>
  );
}

/** Repair-shop batch mode: batches of customers, each with a fix job; statuses live from the jobs API. */
export function ShopClient() {
  const caps = useCapabilities();
  const available = caps.has("get", R2.batches);
  const { admin } = useAdmin();
  const router = useRouter();
  const pathname = usePathname();
  const batchId = useSearchParams().get("batch");
  const qc = useQueryClient();
  const batches = useQuery({ queryKey: ["shop-batches"], queryFn: shop.batches, enabled: available && admin });
  const [name, setName] = React.useState("");
  const create = useMutation({
    mutationFn: (n: string) => shop.create(n),
    onSuccess: (b) => {
      void qc.invalidateQueries({ queryKey: ["shop-batches"] });
      router.push(`${pathname}?batch=${encodeURIComponent(b.id)}`);
    },
  });
  return (
    <>
      <PageHeader
        eyebrow="Repair shops"
        title="Batch mode for repair counters"
        description="Open a batch for the day, add each customer's fix job, and print one A4 job sheet with every verdict, print settings, grams and a price estimate."
      />
      <Container className="space-y-10 py-8">
        {!caps.ready ? (
          <Skeleton className="h-40" />
        ) : !available ? (
          <EmptyState icon={Store} title="Batch mode is not available on this server yet">
            This API does not serve repair-shop batches. Single fixes work as usual from{" "}
            <Link href="/fix" className="text-accent-text underline">
              Fix a part
            </Link>
            .
          </EmptyState>
        ) : !admin ? (
          <AdminAccess what="Batches hold customer names and contacts, so they are admin-only. Enter the shop's admin token to open them on this device." />
        ) : (
          <>
            <AdminLock />
            <form
              className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-5 sm:flex-row sm:items-end"
              onSubmit={(e) => {
                e.preventDefault();
                if (name.trim()) create.mutate(name.trim());
              }}
            >
              <div className="min-w-0 flex-1 space-y-1.5">
                <Label htmlFor="batch-name">New batch</Label>
                <Input id="batch-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Saturday counter, 27 Oct" />
              </div>
              <Button type="submit" variant="primary" disabled={!name.trim() || create.isPending}>
                {create.isPending ? <Spinner className="text-accent-fg" label="Creating" /> : <Plus aria-hidden />} Create batch
              </Button>
            </form>
            {create.isError ? <ErrorState error={create.error} compact what="the batch" /> : null}
            {batchId ? <BatchView id={batchId} /> : null}
            <Section title="Batches">
              {batches.isPending ? (
                <Skeleton className="h-24" />
              ) : batches.isError ? (
                <ErrorState error={batches.error} what="batches" />
              ) : batches.data.length === 0 ? (
                <EmptyState compact icon={Store} title="No batches yet" />
              ) : (
                <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface">
                  {batches.data.map((b) => (
                    <li key={b.id}>
                      <Link href={`${pathname}?batch=${encodeURIComponent(b.id)}`} className="flex items-center justify-between gap-3 px-4 py-3 hover:bg-surface-2">
                        <span className="font-medium">{b.name}</span>
                        <span className="text-[12px] text-subtle">
                          {b.customers} customer{b.customers === 1 ? "" : "s"} · {b.jobs} job{b.jobs === 1 ? "" : "s"}{b.created_at ? ` · ${timeAgo(b.created_at)}` : ""}
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </>
        )}
      </Container>
    </>
  );
}
