import type { Metadata } from "next";
import { LessonsClient } from "./lessons-client";

export const metadata: Metadata = { title: "Lessons", description: "What the builder learned from past runs: candidate lessons and the ones promoted after evidence." };

export default function LessonsPage() {
  return <LessonsClient />;
}
