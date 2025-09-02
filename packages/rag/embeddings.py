"""
RAGline Embeddings Module

Handles vector embeddings generation, storage, and retrieval operations.
Supports OpenAI embeddings and SentenceTransformers with pgvector backend.
"""

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

# Optional Redis caching
try:
    from packages.cache.redis_cache import RedisCache

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

# Optional dependencies
try:
    import sentence_transformers

    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

try:
    import asyncpg

    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False


logger = logging.getLogger(__name__)


class EmbeddingConfig(BaseModel):
    """Configuration for embedding operations."""

    # Provider settings
    provider: str = Field(
        default="openai",
        description="Embedding provider: openai, sentence_transformers",
    )
    model_name: str = Field(default="text-embedding-3-small", description="Model name for embeddings")

    # OpenAI settings
    api_key: Optional[str] = Field(default=None, description="OpenAI API key")
    api_base: Optional[str] = Field(default=None, description="Custom OpenAI API base URL")

    # Vector settings
    dimensions: int = Field(default=1536, description="Vector dimensions")
    normalize: bool = Field(default=True, description="Normalize vectors")

    # Database settings
    database_url: Optional[str] = Field(default=None, description="PostgreSQL connection URL")
    table_name: str = Field(default="embeddings", description="Table name for vector storage")

    # Performance settings
    batch_size: int = Field(default=100, description="Batch size for embedding generation")
    max_retries: int = Field(default=3, description="Max retries for API calls")
    request_timeout: float = Field(default=30.0, description="Request timeout in seconds")

    # Caching settings
    enable_cache: bool = Field(default=True, description="Enable Redis caching for embeddings and queries")
    cache_ttl: int = Field(default=3600, description="Cache TTL in seconds (1 hour default)")
    redis_url: Optional[str] = Field(default=None, description="Redis connection URL")


class Document(BaseModel):
    """Document model for embedding storage."""

    id: str = Field(..., description="Unique document ID")
    content: str = Field(..., description="Document content")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Document metadata")
    embedding: Optional[List[float]] = Field(None, description="Document embedding vector")
    created_at: Optional[datetime] = Field(default_factory=datetime.now)
    updated_at: Optional[datetime] = Field(default_factory=datetime.now)


class SimilarityResult(BaseModel):
    """Result from similarity search."""

    document: Document = Field(..., description="Retrieved document")
    score: float = Field(..., description="Similarity score (0-1, higher is more similar)")
    distance: float = Field(..., description="Vector distance (lower is more similar)")


class EmbeddingProvider:
    """Abstract base for embedding providers."""

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        raise NotImplementedError

    async def embed_query(self, query: str) -> List[float]:
        """Generate embedding for a single query."""
        embeddings = await self.embed_texts([query])
        return embeddings[0]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embedding provider."""

    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.api_base,
            timeout=config.request_timeout,
            max_retries=config.max_retries,
        )

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using OpenAI API."""
        try:
            response = await self.client.embeddings.create(
                model=self.config.model_name,
                input=texts,
                dimensions=self.config.dimensions if self.config.model_name.startswith("text-embedding-3") else None,
            )

            embeddings = [embedding.embedding for embedding in response.data]

            # Normalize if requested
            if self.config.normalize:
                embeddings = [self._normalize_vector(emb) for emb in embeddings]

            return embeddings

        except Exception as e:
            logger.error(f"OpenAI embedding generation failed: {e}")
            raise

    def _normalize_vector(self, vector: List[float]) -> List[float]:
        """Normalize vector to unit length."""
        norm = np.linalg.norm(vector)
        if norm == 0:
            return vector
        return (np.array(vector) / norm).tolist()


class SentenceTransformersProvider(EmbeddingProvider):
    """SentenceTransformers embedding provider."""

    def __init__(self, config: EmbeddingConfig):
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise ImportError("sentence-transformers not installed")

        self.config = config
        self.model = sentence_transformers.SentenceTransformer(config.model_name)

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using SentenceTransformers."""
        try:
            # Run in thread pool since SentenceTransformers is not async
            loop = asyncio.get_event_loop()
            embeddings = await loop.run_in_executor(
                None,
                self.model.encode,
                texts,
                {"normalize_embeddings": self.config.normalize},
            )

            return embeddings.tolist()

        except Exception as e:
            logger.error(f"SentenceTransformers embedding generation failed: {e}")
            raise


class VectorStore:
    """pgvector-based vector storage and retrieval."""

    def __init__(self, config: EmbeddingConfig):
        if not POSTGRES_AVAILABLE:
            raise ImportError("asyncpg not installed")

        self.config = config
        self.pool: Optional[asyncpg.Pool] = None
        self._prepared_statements: Dict[str, str] = {}

        # Initialize Redis cache if available and enabled
        self.cache: Optional[RedisCache] = None
        if config.enable_cache and REDIS_AVAILABLE:
            self.cache = RedisCache(
                redis_url=config.redis_url, default_ttl=config.cache_ttl, key_prefix="ragline_embeddings"
            )

    async def initialize(self):
        """Initialize database connection and create tables."""
        if not self.config.database_url:
            raise ValueError("Database URL required for vector storage")

        try:
            self.pool = await asyncpg.create_pool(self.config.database_url, min_size=1, max_size=10)

            # Register pgvector types
            async with self.pool.acquire() as conn:
                await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                # Register vector type with asyncpg
                try:
                    import pgvector.asyncpg

                    await pgvector.asyncpg.register_vector(conn)
                except ImportError:
                    logger.warning("pgvector.asyncpg not available, using manual vector handling")

            # Create tables and indexes
            await self._create_schema()

            # Prepare optimized SQL statements
            await self._prepare_statements()

            logger.info("Vector store initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize vector store: {e}")
            raise

    async def _create_schema(self):
        """Create database schema for vector storage."""
        async with self.pool.acquire() as conn:
            # Enable pgvector extension
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")

            # Create embeddings table
            create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS {self.config.table_name} (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                metadata JSONB DEFAULT '{{}}',
                embedding vector({self.config.dimensions}),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            """
            await conn.execute(create_table_sql)

            # Create vector index for similarity search
            index_sql = f"""
            CREATE INDEX IF NOT EXISTS {self.config.table_name}_embedding_idx
            ON {self.config.table_name}
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
            """
            await conn.execute(index_sql)

            # Create metadata GIN index
            metadata_index_sql = f"""
            CREATE INDEX IF NOT EXISTS {self.config.table_name}_metadata_idx
            ON {self.config.table_name}
            USING gin (metadata);
            """
            await conn.execute(metadata_index_sql)

    async def _prepare_statements(self):
        """Prepare optimized SQL statements for better performance."""
        async with self.pool.acquire() as conn:
            # Prepare upsert statement
            self._prepared_statements["upsert"] = f"""
                INSERT INTO {self.config.table_name}
                (id, content, metadata, embedding, updated_at)
                VALUES ($1, $2, $3, $4, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    content = EXCLUDED.content,
                    metadata = EXCLUDED.metadata,
                    embedding = EXCLUDED.embedding,
                    updated_at = NOW()
            """

            # Prepare similarity search base query
            self._prepared_statements["similarity_search_base"] = f"""
                SELECT
                    id, content, metadata, embedding, created_at, updated_at,
                    1 - (embedding <=> $1) as similarity,
                    embedding <=> $1 as distance
                FROM {self.config.table_name}
            """

            # Prepare delete statement
            self._prepared_statements["delete"] = f"""
                DELETE FROM {self.config.table_name} WHERE id = ANY($1)
            """

            # Prepare single document lookup
            self._prepared_statements["get_by_id"] = f"""
                SELECT * FROM {self.config.table_name} WHERE id = $1
            """

    async def upsert_documents(self, documents: List[Document]):
        """Insert or update documents with embeddings."""
        if not self.pool:
            await self.initialize()

        async with self.pool.acquire() as conn:
            for doc in documents:
                # Handle metadata JSON serialization
                if isinstance(doc.metadata, dict):
                    metadata_json = json.dumps(doc.metadata)
                elif doc.metadata is None:
                    metadata_json = "{}"
                else:
                    metadata_json = str(doc.metadata)

                await conn.execute(
                    self._prepared_statements["upsert"],
                    doc.id,
                    doc.content,
                    metadata_json,
                    doc.embedding,  # Pass list directly - asyncpg handles pgvector conversion
                )

        logger.info(f"Upserted {len(documents)} documents")

    def _build_cache_key(
        self, query_embedding: List[float], limit: int, threshold: float, filters: Optional[Dict[str, Any]] = None
    ) -> str:
        """Build cache key for similarity search."""
        # Create a hash of search parameters for caching
        params = {
            "embedding_hash": hashlib.sha256(str(query_embedding).encode()).hexdigest()[:16],
            "limit": limit,
            "threshold": threshold,
            "filters": filters or {},
        }
        params_str = json.dumps(params, sort_keys=True)
        cache_hash = hashlib.sha256(params_str.encode()).hexdigest()[:12]
        return f"similarity_search:{cache_hash}"

    async def similarity_search(
        self,
        query_embedding: List[float],
        limit: int = 10,
        threshold: float = 0.5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SimilarityResult]:
        """Perform similarity search using cosine similarity with caching."""
        if not self.pool:
            await self.initialize()

        # Try cache first if enabled
        cache_key = None
        if self.cache:
            cache_key = self._build_cache_key(query_embedding, limit, threshold, filters)
            try:
                cache_client = await self.cache.get_client()
                cached_result = await cache_client.get(f"ragline_embeddings:search:{cache_key}")
                if cached_result:
                    # Deserialize cached results
                    cached_data = json.loads(cached_result)
                    results = []
                    for item in cached_data:
                        doc = Document(**item["document"])
                        results.append(SimilarityResult(document=doc, score=item["score"], distance=item["distance"]))
                    logger.info(f"Cache hit for similarity search: {len(results)} results")
                    return results
            except Exception as e:
                logger.warning(f"Cache lookup failed: {e}")

        # asyncpg handles pgvector conversion automatically
        # Build WHERE clause for metadata filtering
        where_clause = "WHERE 1=1"
        params = [query_embedding, limit]
        param_idx = 3

        if filters:
            for key, value in filters.items():
                where_clause += f" AND metadata->>${param_idx} = ${param_idx + 1}"
                params.extend([key, str(value)])
                param_idx += 2

        # Add similarity threshold
        where_clause += f" AND (1 - (embedding <=> $1)) >= ${param_idx}"
        params.append(threshold)

        # Build optimized query using prepared statement base
        query_sql = f"""
        {self._prepared_statements["similarity_search_base"]}
        {where_clause}
        ORDER BY embedding <=> $1
        LIMIT $2
        """

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query_sql, *params)

        results = []
        for row in rows:
            # Parse metadata if it's a string
            metadata = row["metadata"]
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            elif metadata is None:
                metadata = {}

            doc = Document(
                id=row["id"],
                content=row["content"],
                metadata=metadata,
                embedding=list(row["embedding"]) if row["embedding"] is not None else None,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

            result = SimilarityResult(
                document=doc,
                score=float(row["similarity"]),
                distance=float(row["distance"]),
            )
            results.append(result)

        # Cache results if caching is enabled
        if self.cache and cache_key and results:
            try:
                # Serialize results for caching
                cache_data = []
                for result in results:
                    cache_data.append(
                        {"document": result.document.dict(), "score": result.score, "distance": result.distance}
                    )

                cache_client = await self.cache.get_client()
                await cache_client.setex(
                    f"ragline_embeddings:search:{cache_key}", self.config.cache_ttl, json.dumps(cache_data)
                )
                logger.info(f"Cached {len(results)} search results for {self.config.cache_ttl}s")
            except Exception as e:
                logger.warning(f"Cache store failed: {e}")

        return results

    async def delete_documents(self, document_ids: List[str]):
        """Delete documents by IDs."""
        if not self.pool:
            await self.initialize()

        async with self.pool.acquire() as conn:
            await conn.execute(self._prepared_statements["delete"], document_ids)

        logger.info(f"Deleted {len(document_ids)} documents")

    async def get_document(self, document_id: str) -> Optional[Document]:
        """Retrieve document by ID."""
        if not self.pool:
            await self.initialize()

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(self._prepared_statements["get_by_id"], document_id)

        if row:
            return Document(
                id=row["id"],
                content=row["content"],
                metadata=row["metadata"],
                embedding=list(row["embedding"]) if row["embedding"] else None,
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

        return None

    async def close(self):
        """Close database connection pool."""
        if self.pool:
            await self.pool.close()


class EmbeddingManager:
    """Main interface for embedding operations."""

    def __init__(self, config: EmbeddingConfig):
        self.config = config

        # Initialize provider
        if config.provider == "openai":
            self.provider = OpenAIEmbeddingProvider(config)
        elif config.provider == "sentence_transformers":
            self.provider = SentenceTransformersProvider(config)
        else:
            raise ValueError(f"Unsupported provider: {config.provider}")

        # Initialize vector store
        self.vector_store = VectorStore(config)

    def generate_document_id(self, content: str, metadata: Dict[str, Any] = None) -> str:
        """Generate deterministic document ID from content and metadata."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        if metadata:
            metadata_str = str(sorted(metadata.items()))
            metadata_hash = hashlib.sha256(metadata_str.encode()).hexdigest()[:8]
            return f"doc_{content_hash}_{metadata_hash}"

        return f"doc_{content_hash}"

    async def add_documents(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        document_ids: Optional[List[str]] = None,
    ) -> List[str]:
        """Add documents to the vector store with embeddings."""

        if metadatas is None:
            metadatas = [{}] * len(texts)

        if document_ids is None:
            document_ids = [self.generate_document_id(text, metadata) for text, metadata in zip(texts, metadatas)]

        # Generate embeddings
        embeddings = await self.provider.embed_texts(texts)

        # Create document objects
        documents = [
            Document(id=doc_id, content=text, metadata=metadata, embedding=embedding)
            for doc_id, text, metadata, embedding in zip(document_ids, texts, metadatas, embeddings)
        ]

        # Store in vector database
        await self.vector_store.upsert_documents(documents)

        return document_ids

    async def search(
        self,
        query: str,
        limit: int = 10,
        threshold: float = 0.5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SimilarityResult]:
        """Search for similar documents."""

        # Generate query embedding
        query_embedding = await self.provider.embed_query(query)

        # Perform similarity search
        results = await self.vector_store.similarity_search(
            query_embedding=query_embedding,
            limit=limit,
            threshold=threshold,
            filters=filters,
        )

        return results

    async def delete_documents(self, document_ids: List[str]):
        """Delete documents from vector store."""
        await self.vector_store.delete_documents(document_ids)

    async def get_document(self, document_id: str) -> Optional[Document]:
        """Retrieve document by ID."""
        return await self.vector_store.get_document(document_id)

    async def close(self):
        """Close connections and cleanup."""
        await self.vector_store.close()


# Convenience functions
async def create_embedding_manager(
    provider: str = "openai",
    api_key: Optional[str] = None,
    database_url: Optional[str] = None,
    **kwargs,
) -> EmbeddingManager:
    """Create and initialize embedding manager."""

    config = EmbeddingConfig(provider=provider, api_key=api_key, database_url=database_url, **kwargs)

    manager = EmbeddingManager(config)
    await manager.vector_store.initialize()

    return manager
