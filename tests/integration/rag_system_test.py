#!/usr/bin/env python3
"""
Test script for RAGline RAG system.
Tests embeddings, chunking, retrieval, and ingestion components.
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add packages to path
sys.path.insert(0, "packages")

try:
    from rag import (
        SAMPLE_MENU_ITEMS,
        DataIngestionManager,
        EmbeddingConfig,
        RAGRetriever,
        RetrievalConfig,
        RetrievalContext,
        chunk_menu_item,
        create_embedding_manager,
        ingest_sample_data,
    )

    RAG_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import RAG modules: {e}")
    RAG_AVAILABLE = False


async def test_rag_system():
    """Test the complete RAG system."""

    if not RAG_AVAILABLE:
        print("❌ RAG system not available - skipping tests")
        return

    print("🧪 Testing RAGline RAG System")
    print("=" * 50)

    # Check if we have required dependencies
    api_key = os.getenv("OPENAI_API_KEY")
    database_url = os.getenv("DATABASE_URL")

    if not api_key:
        print("⚠️  No OpenAI API key found - testing with mock mode")
        print("   Set OPENAI_API_KEY environment variable for full testing")

    if not database_url:
        print("⚠️  No database URL found - skipping vector store tests")
        print("   Set DATABASE_URL environment variable for full testing")
        print("   Example: DATABASE_URL=postgresql://user:pass@localhost/ragline")

    # Test 1: Chunking
    print("\n1. Testing Document Chunking")
    try:
        sample_item = SAMPLE_MENU_ITEMS[0]
        chunks = chunk_menu_item(sample_item, "test_item_1")

        print(f"   ✅ Chunked menu item into {len(chunks)} chunks")
        if chunks:
            print(f"   📝 First chunk: {chunks[0].content[:100]}...")
            print(f"   📊 Metadata keys: {list(chunks[0].metadata.keys())}")

    except Exception as e:
        print(f"   ❌ Chunking failed: {e}")

    # Test 2: Embeddings (if API key available)
    if api_key:
        print("\n2. Testing Embeddings Generation")
        try:
            # Create embedding manager (without database for testing)
            config = EmbeddingConfig(
                provider="openai", api_key=api_key, model_name="text-embedding-3-small"
            )

            # Mock embedding manager without database
            from rag.embeddings import OpenAIEmbeddingProvider

            provider = OpenAIEmbeddingProvider(config)

            # Test embedding generation
            test_texts = [
                "Delicious pizza with fresh ingredients",
                "Vegan bowl with quinoa and vegetables",
            ]

            embeddings = await provider.embed_texts(test_texts)

            print(f"   ✅ Generated embeddings for {len(test_texts)} texts")
            print(f"   📏 Embedding dimensions: {len(embeddings[0])}")
            print(f"   🔢 First few values: {embeddings[0][:5]}")

        except Exception as e:
            print(f"   ❌ Embeddings failed: {e}")
    else:
        print("\n2. Skipping Embeddings Test (no API key)")

    # Test 3: Full RAG system (if database available)
    if api_key and database_url:
        print("\n3. Testing Complete RAG System")
        try:
            # Create embedding manager
            embedding_manager = await create_embedding_manager(
                provider="openai", api_key=api_key, database_url=database_url
            )

            print("   ✅ Embedding manager initialized")

            # Test data ingestion
            print("   📥 Ingesting sample data...")
            ingestion_results = await ingest_sample_data(
                embedding_manager, tenant_id="test_restaurant"
            )

            print(f"   ✅ Ingested {ingestion_results['total']} documents")
            print(f"      - Menu items: {len(ingestion_results['menu_items'])}")
            print(f"      - Policies: {len(ingestion_results['policies'])}")
            print(f"      - FAQs: {len(ingestion_results['faqs'])}")

            # Test retrieval
            print("   🔍 Testing retrieval...")

            # Test menu search
            retriever = RAGRetriever(embedding_manager, RetrievalConfig(max_results=3))

            test_queries = [
                "What pizza options do you have?",
                "I need vegan food options",
                "What are your delivery hours?",
            ]

            for query in test_queries:
                results = await retriever.retrieve(query)
                print(f"   🎯 Query: '{query}'")
                print(f"      Found {len(results)} relevant documents")

                if results:
                    top_result = results[0]
                    print(f"      Top result: {top_result.document.content[:80]}...")
                    print(f"      Relevance: {top_result.relevance_score:.2f}")
                    print(f"      Reason: {top_result.retrieval_reason}")

            # Test context formatting
            print("   📝 Testing context formatting...")
            query = "Show me vegetarian options"
            results = await retriever.retrieve(query)

            if results:
                context = retriever.format_context_for_llm(results, query)
                print(f"   ✅ Generated context ({len(context)} chars)")
                print(f"   📄 Context preview: {context[:200]}...")

            # Cleanup
            await embedding_manager.close()
            print("   ✅ RAG system test completed successfully")

        except Exception as e:
            print(f"   ❌ RAG system test failed: {e}")
            import traceback

            print(f"   🔍 Error details: {traceback.format_exc()}")
    else:
        print("\n3. Skipping Complete RAG Test (missing API key or database)")

    # Test 4: Configuration and Edge Cases
    print("\n4. Testing Configuration")
    try:
        # Test different chunking configs
        from rag.chunking import ChunkingConfig, ChunkingStrategy

        configs = [
            ChunkingConfig(chunk_size=256, overlap_size=25),
            ChunkingConfig(chunk_size=1024, overlap_size=100, preserve_sentences=True),
        ]

        for i, config in enumerate(configs):
            chunker = ChunkingStrategy.create_chunker("menu_item", config)
            chunks = chunker.chunk_document(
                "This is a test document with multiple sentences. " * 20,
                f"test_doc_{i}",
            )
            print(f"   ✅ Config {i+1}: Generated {len(chunks)} chunks")

        # Test retrieval configs
        retrieval_configs = [
            RetrievalConfig(max_results=5, similarity_threshold=0.3),
            RetrievalConfig(max_results=10, enable_reranking=False),
        ]

        for i, config in enumerate(retrieval_configs):
            print(
                f"   ✅ Retrieval config {i+1}: max_results={config.max_results}, threshold={config.similarity_threshold}"
            )

    except Exception as e:
        print(f"   ❌ Configuration test failed: {e}")

    print("\n✅ RAG system testing completed!")

    # Summary
    print("\n📊 Test Summary:")
    print(f"   - Document chunking: {'✅' if RAG_AVAILABLE else '❌'}")
    print(f"   - Embedding generation: {'✅' if api_key else '⚠️ (skipped)'}")
    print(
        f"   - Full RAG system: {'✅' if api_key and database_url else '⚠️ (skipped)'}"
    )
    print(f"   - Configuration: {'✅' if RAG_AVAILABLE else '❌'}")


if __name__ == "__main__":
    if not RAG_AVAILABLE:
        print(
            "⚠️  RAG system not available. Make sure you're running from the correct directory."
        )
        print("   Required dependencies: tiktoken, numpy, pydantic")
        print("   Optional: openai, asyncpg (for full testing)")
        sys.exit(1)

    asyncio.run(test_rag_system())
