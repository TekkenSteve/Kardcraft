import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  trailingSlash: false,
  images: {
    unoptimized: true,
  },
  async rewrites() {
    return [
      {
        // Proxy to API Gateway (APISIX) - handles both API and auth routes
        source: "/api/:path*",
        destination: "http://localhost:9080/api/:path*",
      },
      {
        // Proxy to API Gateway (APISIX) - handles Kratos auth
        source: "/auth/:path*",
        destination: "http://localhost:9080/auth/:path*",
      },
    ];
  },
  async headers() {
    return [
      {
        // Apply headers to all API routes
        source: "/api/:path*",
        headers: [
          {
            key: "Access-Control-Allow-Credentials",
            value: "true",
          },
        ],
      },
      {
        // Apply headers to all auth routes
        source: "/auth/:path*",
        headers: [
          {
            key: "Access-Control-Allow-Credentials",
            value: "true",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
