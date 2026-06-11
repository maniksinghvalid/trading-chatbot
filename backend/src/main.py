"""
main.py — FastAPI application entry point.

Creates the `app` instance, configures CORSMiddleware, and includes all routers.
This module is the uvicorn entry point: `uvicorn src.main:app --reload`
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.routes.admin import router as admin_router
from src.routes.auth import router as auth_router
from src.routes.chat import router as chat_router
from src.routes.health import router as health_router
from src.routes.quote import router as quote_router
from src.routes.sessions import router as sessions_router
from src.session_store import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create DB tables at startup (NOT at import) so a momentarily-unreachable
    # database doesn't break module import or the test suite. See init_db().
    init_db()
    yield


app = FastAPI(
    title="Trading Chatbot Backend",
    description="RAG-powered trading research chatbot backed by Pinecone + OpenAI.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow origins from settings (default: http://localhost:3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(quote_router)
app.include_router(sessions_router)
app.include_router(admin_router)
