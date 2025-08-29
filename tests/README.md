# RAGline LLM Service Tests

This directory contains tests and examples for the LLM service components.

## Directory Structure

### `examples/`
Demonstration scripts showing how to use each system component:
- `llm_client_example.py` - OpenAI integration and configuration examples
- `rag_system_demo.py` - Complete RAG workflow demonstration

### `integration/`
Integration tests for validating system functionality:
- `tools_integration_test.py` - Tool system validation and testing
- `rag_system_test.py` - Full RAG system testing (requires database)

## Running Tests

### Prerequisites
```bash
# Activate virtual environment
source .venv/bin/activate

# Ensure environment variables are set
export OPENAI_API_KEY=your_key_here
export DATABASE_URL=postgresql://user:pass@localhost:5432/ragline  # for full tests
```

### Examples (Safe to run anytime)
```bash
# Test LLM client configuration and basic functionality
python tests/examples/llm_client_example.py

# Demonstrate complete RAG workflow with performance metrics
python tests/examples/rag_system_demo.py
```

### Integration Tests (Requires setup)
```bash
# Test all tools with mock data
python tests/integration/tools_integration_test.py

# Test complete RAG system (requires PostgreSQL with pgvector)
python tests/integration/rag_system_test.py
```

## Test Coverage

- ✅ LLM client configuration and OpenAI integration
- ✅ Tool system functionality and validation
- ✅ RAG document processing and chunking
- ✅ Vector embedding generation and search
- ✅ Business rule re-ranking and user preferences
- ✅ Error handling and edge cases
- ✅ Performance metrics and benchmarking

## Performance Targets

- Document processing: < 50ms per item
- Embedding generation: < 100ms per text
- Vector search: < 30ms p95 (with pgvector)
- Tool execution: < 200ms p95
- Complete RAG pipeline: < 500ms p95
