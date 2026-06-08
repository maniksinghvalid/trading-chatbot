"""
main.py — FastAPI application entry point.

Creates the `app` instance, configures CORSMiddleware, and includes all routers.
This module is the uvicorn entry point: `uvicorn src.main:app --reload`
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.routes.chat import router as chat_router
from src.routes.health import router as health_router

app = FastAPI(
    title="Trading Chatbot Backend",
    description="RAG-powered trading research chatbot backed by Pinecone + OpenAI.",
    version="0.1.0",
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
app.include_router(chat_router)
