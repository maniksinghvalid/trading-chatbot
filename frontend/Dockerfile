# frontend/Dockerfile — Next.js production build image
#
# Builds the Next.js app and runs `next start`.
# NEXT_PUBLIC_API_BASE must be set at build time (ARG) so the bundled client
# JS knows the backend URL.  It can also be overridden at runtime via env.
#
# Build with:
#   docker build \
#     --build-arg NEXT_PUBLIC_API_BASE=https://your-backend.example.com \
#     -t chatbot-frontend .
# (from trading-chatbot/frontend/)

FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files first for layer-cache efficiency
COPY package.json package-lock.json ./

# Install all dependencies (dev + prod needed for build)
RUN npm ci

# Build-time public env var — set to the deployed backend URL
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}

# Copy the full source and build
COPY . .
RUN npm run build

# ---- runtime stage -------------------------------------------------------
FROM node:20-alpine AS runtime

WORKDIR /app

ENV NODE_ENV=production

# Copy the built output and runtime dependencies from builder
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public 2>/dev/null || true
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/package-lock.json ./package-lock.json
COPY --from=builder /app/next.config.mjs ./next.config.mjs

# Install production-only dependencies
RUN npm ci --omit=dev

# Non-root user for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser

# Allow runtime override of the API base (for platforms that inject env at container start)
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}

EXPOSE 3000

CMD ["npm", "run", "start"]
