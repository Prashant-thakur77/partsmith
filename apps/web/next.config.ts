import type { NextConfig } from "next";

const apiUrl = (process.env.API_URL ?? "http://localhost:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
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

export default nextConfig;
