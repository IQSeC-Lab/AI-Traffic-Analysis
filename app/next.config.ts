import type { NextConfig } from "next";

// FastAPI backend in api/index.py. Read at build time for `next build`.
const apiUrl = process.env.API_URL ?? "http://127.0.0.1:8000";

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
