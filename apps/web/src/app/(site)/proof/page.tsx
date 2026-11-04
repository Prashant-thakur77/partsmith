import type { Metadata } from "next";
import { ProofClient } from "./proof-client";

export const metadata: Metadata = {
  title: "Proof",
  description: "What PartSmith has been tested on, each result with its ground truth and the command to reproduce it, and what has not been tested yet.",
};

export default function ProofPage() {
  return <ProofClient />;
}
