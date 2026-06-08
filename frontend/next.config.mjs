/** @type {import('next').NextConfig} */
const nextConfig = {
  // Proxy /api/chat/stream to the FastAPI backend during development
  // In production, set NEXT_PUBLIC_API_BASE to the backend URL
};

export default nextConfig;
