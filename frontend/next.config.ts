import type { NextConfig } from "next";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    // Same-origin proxy: /api/* routes through Next.js server to FastAPI backend.
    // Credentials and cookies flow naturally; no browser CORS issues.
    return {
      beforeFiles: [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }],
    };
  },
};

export default nextConfig;
