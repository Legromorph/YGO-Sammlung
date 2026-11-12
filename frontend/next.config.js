/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  // Card images are served by the backend; no next/image optimisation (and no
  // platform-specific sharp binary) is needed.
  images: { unoptimized: true },
};

module.exports = nextConfig;
