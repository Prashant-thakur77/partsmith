import type { Metadata } from "next";
import { AdminClient } from "@/components/admin/admin-client";

export const metadata: Metadata = {
  title: "Admin",
  description: "Admin console: overview, registry moderation, taught rules, audit log and demand.",
  robots: { index: false, follow: false },
};

export default function AdminPage() {
  return <AdminClient />;
}
