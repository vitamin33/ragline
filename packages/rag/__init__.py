# RAG package
from .embeddings import (
    EmbeddingManager,
    EmbeddingConfig,
    Document,
    SimilarityResult,
    create_embedding_manager
)

from .chunking import (
    Chunk,
    ChunkingConfig,
    ChunkingStrategy,
    chunk_menu_item,
    chunk_policy_document
)

from .retrieval import (
    RAGRetriever,
    RetrievalConfig,
    RetrievalContext,
    RetrievedDocument,
    retrieve_menu_items,
    retrieve_policies
)

from .ingestion import (
    DataIngestionManager,
    ingest_sample_data,
    SAMPLE_MENU_ITEMS,
    SAMPLE_POLICY_DOCUMENTS,
    SAMPLE_FAQ_ITEMS
)

__all__ = [
    # Embeddings
    "EmbeddingManager",
    "EmbeddingConfig", 
    "Document",
    "SimilarityResult",
    "create_embedding_manager",
    
    # Chunking
    "Chunk",
    "ChunkingConfig",
    "ChunkingStrategy",
    "chunk_menu_item",
    "chunk_policy_document",
    
    # Retrieval
    "RAGRetriever",
    "RetrievalConfig",
    "RetrievalContext",
    "RetrievedDocument",
    "retrieve_menu_items", 
    "retrieve_policies",
    
    # Ingestion
    "DataIngestionManager",
    "ingest_sample_data",
    "SAMPLE_MENU_ITEMS",
    "SAMPLE_POLICY_DOCUMENTS",
    "SAMPLE_FAQ_ITEMS",
]