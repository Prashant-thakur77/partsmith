import bundleAnalyzer from "@next/bundle-analyzer";
import type { NextConfig } from "next";

// Same rule as src/lib/api-origin.ts (kept inline: the config is evaluated before the app's modules).
const apiUrl = (process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Put generated <meta> (titles, descriptions) in <head> for every client, not only known bots.
  htmlLimitedBots: /.*/,
  async rewrites() {
    // `fallback` runs after app routes (incl. dynamic ones), so src/app/api/v1/jobs/[id]/events can stream SSE unbuffered.
    return {
      beforeFiles: [],
      afterFiles: [],
      fallback: [
        { source: "/api/v1/:path*", destination: `${apiUrl}/api/v1/:path*` },
        // MCP (streamable HTTP) is mounted on the API app; expose it on the web origin too.
        { source: "/mcp", destination: `${apiUrl}/mcp` },
        { source: "/mcp/:path*", destination: `${apiUrl}/mcp/:path*` },
      ],
    };
  },
  // Plain-word routes (round 2); old links keep working.
  async redirects() {
    return [
      { source: "/bench", destination: "/results", permanent: true },
      { source: "/steer", destination: "/factory", permanent: true },
      { source: "/status", destination: "/models", permanent: true },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        ],
      },
    ];
  },
};

// `ANALYZE=1 pnpm build` writes .next/analyze/client.json (module sizes per chunk).
const withAnalyzer = bundleAnalyzer({ enabled: process.env.ANALYZE === "1", openAnalyzer: false, analyzerMode: "json" });

export default withAnalyzer(nextConfig);
