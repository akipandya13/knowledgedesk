/** @type {import('next').NextConfig} */

// All browser calls go to the same origin under /api/*. In dev (and in the
// bundled Docker image) Next proxies those to the FastAPI backend so there is
// no CORS and no base-URL juggling in the client code.
const API_TARGET = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  // ESLint is not part of the container build; type-checking still runs.
  eslint: { ignoreDuringBuilds: true },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_TARGET}/api/:path*` },
    ];
  },
};

export default nextConfig;
