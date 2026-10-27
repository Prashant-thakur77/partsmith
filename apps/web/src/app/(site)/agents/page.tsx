import type { Metadata } from "next";
import { AgentsClient } from "./agents-client";

export const metadata: Metadata = { title: "For agents", description: "REST, MCP and llms.txt docs for using PartSmith parts from coding agents." };

export default function AgentsPage() {
  return <AgentsClient />;
}
