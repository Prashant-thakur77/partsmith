import type { Metadata } from "next";
import { WorkspaceClient } from "./workspace-client";

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  return { title: `Job ${id}`, robots: { index: false } };
}

export default async function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <WorkspaceClient id={decodeURIComponent(id)} />;
}
