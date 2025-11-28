/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
    return [
      // SSE streaming endpoints - separate to ensure no buffering issues
      {
        source: '/api/scanner/historical/:date/stream',
        destination: `${backendUrl}/api/scanner/historical/:date/stream`
      },
      // All other API routes
      {
        source: '/api/:path*',
        destination: `${backendUrl}/api/:path*`
      }
    ]
  }
}

module.exports = nextConfig
