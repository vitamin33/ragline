# Agent C Unit Tests

Unit tests for LLM & RAG layer components.

## Scope
- LLM client integration (OpenAI, Ollama)
- RAG retrieval and embedding logic
- Chat streaming functionality  
- Tool execution system
- Response processing and validation

## Structure
- `test_llm_*.py` - LLM client and integration tests
- `test_rag_*.py` - RAG system tests
- `test_chat_*.py` - Chat endpoint tests
- `test_tools_*.py` - Tool system tests
- `test_streaming_*.py` - Streaming response tests

## Running  
```bash
pytest tests/unit/agent_c -m agent_c
```