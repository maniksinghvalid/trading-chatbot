# Deployment Guide — Trading Chatbot

This guide documents how to deploy the trading-chatbot stack to production.
Two paths are covered: **managed platform** (recommended) and **self-hosted** via Docker Compose.

---

## Prerequisites

### Platform CLIs

| Tool | Install | Purpose |
|------|---------|---------|
| `flyctl` | `brew install flyctl` or https://fly.io/docs/hands-on/install-flyctl/ | Backend deploy (Fly.io) |
| `vercel` | `npm i -g vercel` | Frontend deploy (Vercel) |
| `docker` + `docker compose` | https://docs.docker.com/get-docker/ | Self-hosted path only |

### Platform accounts

- **Fly.io** (backend) — https://fly.io — free tier covers a single backend instance
- **Vercel** (frontend) — https://vercel.com — free hobby tier works
- **Managed Postgres** — Fly.io Postgres (`fly postgres create`) or Supabase/Neon; URL format: `postgresql+psycopg://user:pass@host:5432/dbname`

---

## Secrets reference

Set **all** of these on the deploy platform before deploying. Never commit them to the repo.

| Secret name | Where to set | Description |
|-------------|-------------|-------------|
| `DATABASE_URL` | Backend | Managed Postgres DSN (`postgresql+psycopg://...`) |
| `PINECONE_READ_KEY` | Backend + CI | Pinecone reader API key (consumer-only) |
| `PINECONE_HOST` | Backend | Pinecone index host URL |
| `OPENAI_API_KEY` | Backend | OpenAI API key |
| `JWT_SECRET` | Backend | Random 32+ byte string for JWT signing |
| `RESEND_API_KEY` | Backend | Resend email provider key (magic-link auth) |
| `MAGIC_LINK_FROM_EMAIL` | Backend | Verified sender address, e.g. `noreply@yourdomain.com` |
| `BACKEND_URL` | Backend | Public HTTPS URL of the backend, e.g. `https://chatbot-backend.fly.dev` |
| `CORS_ORIGINS` | Backend | Comma-separated allowed origins, e.g. `https://chatbot.vercel.app` |
| `NEXT_PUBLIC_API_BASE` | Frontend | Public HTTPS URL of the backend (same as `BACKEND_URL`) |
| `PINECONE_READ_KEY` | GitHub Actions secret | Enables VERIFY-SCHEMA schema-regression test in CI |

Generate a strong JWT_SECRET:
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## Path A: Managed platform (Fly.io backend + Vercel frontend)

### 1. Deploy the backend (Fly.io)

```bash
# Authenticate
fly auth login

# From the repo root — create a new app (first time only)
fly launch --name chatbot-backend --dockerfile trading-chatbot/backend/Dockerfile \
  --source trading-chatbot/backend --region ord --no-deploy

# Set secrets (do this before first deploy)
fly secrets set \
  DATABASE_URL="postgresql+psycopg://user:pass@host:5432/chatbot" \
  PINECONE_READ_KEY="pc-..." \
  PINECONE_HOST="https://trade-reports-xxxx.svc.pinecone.io" \
  OPENAI_API_KEY="sk-..." \
  JWT_SECRET="$(python3 -c "import secrets; print(secrets.token_hex(32))")" \
  RESEND_API_KEY="re_..." \
  MAGIC_LINK_FROM_EMAIL="noreply@yourdomain.com" \
  BACKEND_URL="https://chatbot-backend.fly.dev" \
  CORS_ORIGINS="https://chatbot.vercel.app"

# Deploy
fly deploy --source trading-chatbot/backend --dockerfile trading-chatbot/backend/Dockerfile
```

After deploy, the backend is live at `https://chatbot-backend.fly.dev` (or your custom domain).

> **HTTPS-only:** Fly.io terminates TLS automatically. The backend never serves plain HTTP in
> production — all traffic arrives at the app over HTTPS via the Fly.io edge.

### 2. Deploy the frontend (Vercel)

```bash
# Authenticate
vercel login

# From trading-chatbot/frontend/
cd trading-chatbot/frontend

# First deploy (creates the project)
vercel --prod

# Set the backend URL env var (replace with your actual backend URL)
vercel env add NEXT_PUBLIC_API_BASE production
# → enter: https://chatbot-backend.fly.dev

# Redeploy to pick up the env var
vercel --prod
```

The frontend is live at `https://chatbot-<your-id>.vercel.app` (or your custom domain).

### 3. Wire CORS

Update the backend `CORS_ORIGINS` secret to include the Vercel frontend URL:

```bash
fly secrets set CORS_ORIGINS="https://chatbot-<your-id>.vercel.app"
fly deploy ...
```

### 4. Set the PINECONE_READ_KEY GitHub Actions secret

In your GitHub repo: **Settings → Secrets and variables → Actions → New repository secret**

- Name: `PINECONE_READ_KEY`
- Value: your Pinecone reader key

This enables the VERIFY-SCHEMA schema-regression test to run on every CI commit.

---

## Path B: Self-hosted via Docker Compose

```bash
# 1. Copy and fill in the env file (never commit it)
cp .env.example .env   # or create .env manually with the secrets above

# 2. Build and start all services
NEXT_PUBLIC_API_BASE=https://your-backend-domain.example.com \
docker compose -f docker-compose.production.yml up -d --build

# 3. View logs
docker compose -f docker-compose.production.yml logs -f
```

Expose the frontend port (3000) and backend port (8000) via a reverse proxy (nginx, Caddy)
with TLS. Never serve plain HTTP in production.

```nginx
# Example nginx snippet (HTTPS-only)
server {
    listen 443 ssl;
    server_name chatbot.example.com;
    location / { proxy_pass http://localhost:3000; }
}
server {
    listen 443 ssl;
    server_name api.chatbot.example.com;
    location / { proxy_pass http://localhost:8000; }
}
# Redirect all HTTP → HTTPS
server { listen 80; return 301 https://$host$request_uri; }
```

---

## Post-deploy smoke checklist

Run these checks after every deploy to verify the stack is working end-to-end.

- [ ] `curl -s https://<BACKEND_URL>/health` returns `{"status":"ok"}` (or similar 200 response)
- [ ] Visit the public frontend URL — the login page loads without console errors
- [ ] Request a magic link with your email address — the email arrives within ~30 seconds
- [ ] Click the magic link — you are redirected and land on the chat page (JWT issued)
- [ ] Send the message **"bull case for AAPL"** — a streamed, cited response appears with at least one citation card referencing a stored report
- [ ] The session persists — refresh the page, click the session in the sidebar, and the history is restored
- [ ] Check CI on GitHub — the latest commit shows the VERIFY-SCHEMA backend test as green (or skipped if PINECONE_READ_KEY secret is missing)

### Confirming end-to-end success

When the smoke checklist passes, record the public frontend URL here:

```
Live frontend URL: https://____________________________
Deployed: YYYY-MM-DD
Backend URL: https://____________________________
```

---

## Rollback

```bash
# Fly.io — roll back to previous release
fly releases list
fly deploy --image <previous-image-ref>

# Vercel — roll back to previous deployment
vercel rollback
```

---

## Environment variable reference (.env.example)

A template for the self-hosted path (do not commit with real values):

```dotenv
# Postgres
POSTGRES_PASSWORD=change_me_in_production

# Backend
DATABASE_URL=postgresql+psycopg://chatbot:change_me_in_production@db:5432/chatbot
PINECONE_READ_KEY=pc-...
PINECONE_HOST=https://trade-reports-xxxx.svc.pinecone.io
OPENAI_API_KEY=sk-...
JWT_SECRET=generate_with_secrets_token_hex_32
RESEND_API_KEY=re_...
MAGIC_LINK_FROM_EMAIL=noreply@example.com
BACKEND_URL=https://api.example.com
CORS_ORIGINS=https://example.com

# Frontend
NEXT_PUBLIC_API_BASE=https://api.example.com

# Docker Compose port overrides (optional)
BACKEND_PORT=8000
FRONTEND_PORT=3000
```
