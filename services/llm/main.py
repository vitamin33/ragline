"""
RAGline LLM Service

A FastAPI service for LLM orchestration with RAG capabilities.
Supports OpenAI API and local models via OPENAI_API_BASE override.
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from routers import chat


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan management."""
    # Startup
    print("🚀 RAGline LLM Service starting up...")
    
    # TODO: Initialize LLM client
    # TODO: Load embedding models
    # TODO: Setup RAG components
    
    yield
    
    # Shutdown
    print("📴 RAGline LLM Service shutting down...")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="RAGline LLM Service",
        description="LLM orchestration with RAG capabilities",
        version="1.0.0",
        lifespan=lifespan,
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # TODO: Configure for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Include routers
    app.include_router(chat.router, prefix="/chat", tags=["chat"])
    
    # Health check
    @app.get("/health")
    async def health_check():
        return JSONResponse({"status": "healthy", "service": "llm"})
    
    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("LLM_PORT", 8001))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info"
    )