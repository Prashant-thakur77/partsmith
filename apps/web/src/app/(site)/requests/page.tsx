import type { Metadata } from "next";
import { RequestsClient } from "./requests-client";

export const metadata: Metadata = { title: "Part requests", description: "Parts people asked for that nobody has built yet. Vote, or add your own." };

export default function RequestsPage() {
  return <RequestsClient />;
}
