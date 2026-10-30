import type { Metadata } from "next";
import { Suspense } from "react";
import { FeedbackLogClient } from "./log-client";

export const metadata: Metadata = {
  title: "Feedback log",
  description: "Every time a part was sent back or rejected: what was wrong, why it matters, and what the measurements showed next.",
};

export default function FeedbackLogPage() {
  return (
    <Suspense>
      <FeedbackLogClient />
    </Suspense>
  );
}
