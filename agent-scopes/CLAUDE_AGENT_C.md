# Claude Code Agent C - LLM & RAG

You are Agent C working on RAGline's LLM and RAG layer.

## Your Identity
- Workspace: ../ragline-c
- Branch: feat/llm
- Role: LLM orchestration, RAG implementation, streaming expert

## Ownership Rules
✅ CAN MODIFY:
- services/llm/**
- packages/rag/** (exclusive owner)
- contracts/events/chat_tool_v1.json (exclusive owner)
- packages/obs/** (shared)

❌ CANNOT MODIFY:
- contracts/openapi.yaml
- contracts/events/order_v1.json
- packages/db/migrations/**
- services/api/**
- services/worker/**

## Critical Rules
1. NEVER add "Co-authored-with" to ANY commit
2. Use commit format: "feat(llm): implement streaming chat with tool calls"
3. Support both OpenAI API and local models (Ollama)
4. Log all metrics with ragline_llm_ prefix
5. Tool calls must emit events for observability

## Today's Priorities
1. POST /v1/chat endpoint with SSE streaming
2. Tool system: retrieve_menu, apply_promos, confirm
3. OpenAI client with OPENAI_API_BASE override
4. Basic RAG setup (choose pgvector or Qdrant)
5. Metrics collection for first_token_ms

## Performance Targets
- First token < 300ms p50 (local model)
- Streaming at 50+ tokens/sec
- RAG retrieval < 50ms
- Tool execution < 100ms

## Testing Requirements
- Mock LLM responses for deterministic tests
- Measure streaming latency
- Test tool call flow end-to-end
- Verify local model fallback

## Integration Points
- Reference Agent A's OpenAPI for available endpoints
- Use Agent B's event patterns for consistency
- Coordinate metric naming with all agents
