import type { Metadata } from "next";
import { Suspense } from "react";
import { JobsClient } from "./jobs-client";

export const metadata: Metadata = { title: "Recent jobs", description: "Fix jobs run on this PartSmith instance." };

export default function JobsPage() {
  return (
    <Suspense>
      <JobsClient />
    </Suspense>
  );
}
