# LLM Service Integration Tests

These tests validate the complete functionality of LLM service components in realistic scenarios.

## Integration Tests

### `tools_integration_test.py`
Validates:
- All 3 tools (retrieve_menu, apply_promos, confirm) 
- Tool registration and schema generation
- OpenAI function calling format
- Error handling and validation
- Tool execution with timing metrics

### `rag_system_test.py`
Tests:
- Complete RAG pipeline with real database
- Document ingestion and vector storage
- Similarity search with pgvector
- Business rule application
- Multi-tenant context isolation

## Requirements

### For tools_integration_test.py
- Virtual environment activated
- No external dependencies (uses mock data)

### For rag_system_test.py
- PostgreSQL with pgvector extension
- DATABASE_URL environment variable
- OPENAI_API_KEY for embedding generation

## Expected Results

### Tools Test
- ✅ 3/3 tools registered successfully
- ✅ OpenAI function schemas valid
- ✅ Tool execution under 200ms
- ✅ Error handling working correctly

### RAG Test  
- ✅ Document ingestion and chunking
- ✅ Vector embeddings generated (1536 dimensions)
- ✅ Similarity search under 30ms (with pgvector)
- ✅ Business rules applied correctly
- ✅ LLM context generation under 2000 tokens