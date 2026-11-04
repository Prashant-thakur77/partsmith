import type { Metadata } from "next";
import { GalleryClient } from "./gallery-client";

export const metadata: Metadata = {
  title: "Gallery",
  description: "Every part in the registry and every template as a live 3D model, with what has and hasn't been verified.",
};

export default function GalleryPage() {
  return <GalleryClient />;
}
