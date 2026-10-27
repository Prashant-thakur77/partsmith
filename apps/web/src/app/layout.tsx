import type { Metadata, Viewport } from "next";
import { mono, sans } from "./fonts";
import { Providers } from "@/components/providers";
import { THEME_SCRIPT } from "@/lib/theme";
import "@/styles/globals.css";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: "PartSmith — photo to verified replacement part", template: "%s · PartSmith" },
  description:
    "Photograph a broken plastic part on your screen. PartSmith measures it in millimetres, writes parametric CAD and proves the model matches the photo before you print.",
  applicationName: "PartSmith",
  openGraph: {
    type: "website",
    siteName: "PartSmith",
    title: "PartSmith — photo to verified replacement part",
    description: "Measured from a photo. Written as parametric CAD. Verified by code, not by the model.",
  },
  twitter: { card: "summary_large_image" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbfbfb" },
    { media: "(prefers-color-scheme: dark)", color: "#0e0e0e" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${mono.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body className="min-h-dvh">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
