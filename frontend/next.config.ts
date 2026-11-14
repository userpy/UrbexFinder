import type { NextConfig } from "next";
const config: NextConfig = {
  output: "standalone",
  experimental: {
    // OSINT report can wait on SearXNG; default rewrite proxy is 30s.
    proxyTimeout: 120_000,
  },
  async rewrites() {
    return {
      fallback: [
        {
          source: "/api/:path*",
          destination: `${process.env.API_INTERNAL_URL || "http://127.0.0.1:58000"}/api/:path*`,
        },
      ],
    };
  },
};
export default config;
