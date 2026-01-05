/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Experimental: Allow async headers and suppress warnings
  experimental: {
    serverActions: {
      bodySizeLimit: '2mb',
    },
    missingSuspenseWithCSRBailout: false,
  },
  // Suppress console warnings for known Next.js 15 + Clerk compatibility issues
  onDemandEntries: {
    maxInactiveAge: 60 * 1000,
    pagesBufferLength: 5,
  },
}

module.exports = nextConfig

