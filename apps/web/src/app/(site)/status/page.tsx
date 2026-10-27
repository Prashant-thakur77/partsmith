import type { Metadata } from "next";
import { StatusClient } from "./status-client";

export const metadata: Metadata = { title: "Status", description: "Which model runs each stage, where it runs, whether it is live or a labelled mock, and what it costs." };

export default function StatusPage() {
  return <StatusClient />;
}
