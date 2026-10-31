"use client";

import { ShieldCheck } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { AdminAccess, AdminLock, useAdmin } from "@/components/admin-access";
import { Container, PageHeader } from "@/components/layout/page";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ADMIN_API, ADMIN_TABS, tabFromParam, type AdminTab } from "@/lib/api-admin";
import { useCapabilities } from "@/lib/capabilities";
import { AuditTab } from "./audit-tab";
import { DemandTab } from "./demand-tab";
import { OverviewTab } from "./overview-tab";
import { PartsTab } from "./parts-tab";
import { RulesTab } from "./rules-tab";

/** The admin console: overview, registry moderation, taught rules, audit log and demand. Tab in `?tab=`. */
export function AdminClient() {
  const caps = useCapabilities();
  const { admin } = useAdmin();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const tab = tabFromParam(params.get("tab"));
  const available = caps.has("get", ADMIN_API.overview);
  const setTab = (t: string) => {
    const next = new URLSearchParams(params.toString());
    if (t === "overview") next.delete("tab");
    else next.set("tab", t);
    const qs = next.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  };
  return (
    <>
      <PageHeader compact title="Admin" description="Run the site from one place: how jobs go, what parts are listed, what reviews teach and who changed what." actions={<AdminLock />} />
      <Container className="py-6">
        {!caps.ready ? (
          <Skeleton className="h-64" />
        ) : !available ? (
          <EmptyState icon={ShieldCheck} title="The admin console is not available on this server yet">
            This API does not serve the admin routes. Nothing is shown rather than an example.
          </EmptyState>
        ) : !admin ? (
          <AdminAccess what="The admin console needs the admin token. It is kept on this device only." />
        ) : (
          <Tabs value={tab} onValueChange={(v) => setTab(v as AdminTab)}>
            <TabsList aria-label="Admin sections">
              {ADMIN_TABS.map((t) => (
                <TabsTrigger key={t.id} value={t.id}>
                  {t.label}
                </TabsTrigger>
              ))}
            </TabsList>
            <TabsContent value="overview">
              <OverviewTab />
            </TabsContent>
            <TabsContent value="parts">
              <PartsTab />
            </TabsContent>
            <TabsContent value="rules">
              <RulesTab />
            </TabsContent>
            <TabsContent value="audit">
              <AuditTab />
            </TabsContent>
            <TabsContent value="demand">
              <DemandTab />
            </TabsContent>
          </Tabs>
        )}
      </Container>
    </>
  );
}
