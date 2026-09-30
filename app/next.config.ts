import type { NextConfig } from "next";

// FastAPI backend in api/index.py. API_PORT must match the port the backend runs on
// (the npm scripts use it too); API_URL overrides the whole address. Read at build time for `next build`.
const apiUrl = process.env.API_URL ?? `http://127.0.0.1:${process.env.API_PORT ?? "8000"}`;

const nextConfig: NextConfig = {
  // Keep the dev badge off the sidebar
  devIndicators: { position: "bottom-right" },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
