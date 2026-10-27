import type { Metadata } from "next";
import { JudgesClient } from "./judges-client";

export const metadata: Metadata = { title: "Judges", description: "The 30-second judge path: a replayed run, the bench, model status and agent docs." };

export default function JudgesPage() {
  return <JudgesClient />;
}
