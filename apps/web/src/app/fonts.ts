import { Geist, Geist_Mono } from "next/font/google";

/** UI font: Latin subset, self-hosted at build time, preloaded, size-adjusted fallback so the swap does not shift layout. */
export const sans = Geist({ subsets: ["latin"], variable: "--font-geist-sans", display: "swap", adjustFontFallback: true });

/** Numbers and code: Latin subset, not preloaded (never the first paint's critical text). */
export const mono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono", display: "swap", preload: false });
