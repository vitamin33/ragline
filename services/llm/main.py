"""
RAGline LLM Service

A FastAPI service for LLM orchestration with RAG capabilities.
Supports OpenAI API and local models via OPENAI_API_BASE override.
"""

import os
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv

# Add project root to Python path for package imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# Load environment variables from project root
load_dotenv("../../.env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from routers import chat, registry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan management."""
    # Startup
    print("🚀 RAGline LLM Service starting up...")

    # Initialize LLM client
    from packages.rag.llm_client import LLMClient, LLMConfig

    llm_config = LLMConfig(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_API_BASE"),
        model=os.getenv("OPENAI_MODEL", "gpt-4"),
        temperature=0.7,
        max_tokens=1500,
        request_timeout=30.0,
    )

    app.state.llm_client = LLMClient(llm_config)
    print("✅ LLM client initialized")

    # Load embedding models for RAG (graceful degradation if DB unavailable)
    try:
        from packages.rag.embeddings import EmbeddingConfig, create_embedding_manager

        embedding_config = EmbeddingConfig(
            provider="openai",
            api_key=os.getenv("OPENAI_API_KEY"),
            api_base=os.getenv("OPENAI_API_BASE"),
            database_url=os.getenv("DATABASE_URL", "postgresql://ragline_user:secure_password@localhost:5433/ragline"),
            enable_cache=True,
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        )

        app.state.embedding_manager = await create_embedding_manager(
            provider=embedding_config.provider,
            api_key=embedding_config.api_key,
            database_url=embedding_config.database_url,
            config=embedding_config,
        )
        print("✅ Embedding manager initialized")

    except Exception as e:
        print(f"⚠️  Warning: Could not initialize embedding manager: {e}")
        print("📝 LLM service will run with limited RAG capabilities")
        app.state.embedding_manager = None

    # Setup RAG components - initialize enhanced tool manager with dynamic registry
    from services.llm.registry.dynamic_registry import get_dynamic_registry
    from services.llm.tools.enhanced_manager import get_enhanced_tool_manager

    app.state.tool_manager = await get_enhanced_tool_manager()
    app.state.dynamic_registry = await get_dynamic_registry()
    print("✅ Enhanced tool manager with dynamic registry initialized")

    print("🎉 RAGline LLM Service ready!")

    yield

    # Shutdown
    print("📴 RAGline LLM Service shutting down...")

    # Cleanup embedding manager
    if hasattr(app.state, "embedding_manager"):
        await app.state.embedding_manager.close()
        print("✅ Embedding manager closed")

    print("👋 RAGline LLM Service shutdown complete")


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
    app.include_router(registry.router, prefix="/registry", tags=["tool_registry"])

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
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True, log_level="info")
