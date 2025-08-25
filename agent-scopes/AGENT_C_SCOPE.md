# Agent C: LLM & RAG

## Ownership
- **Exclusive**: services/llm/, packages/rag/, contracts/events/chat_tool_v1.json
- **Shared**: packages/obs/
- **Read-only**: All other directories

## Deliverables
1. POST /v1/chat with SSE/WS streaming
2. Tool-using flow: retrieve_menu → apply_promos → confirm
3. RAG over menu data via pgvector or Qdrant
4. Local model support via OpenAI-compatible endpoint (Ollama/vLLM)
5. Metrics: ragline_llm_first_token_ms, ragline_llm_latency_ms, ragline_llm_tokens_total
6. Voice gateway with ASR (optional week 2)

## Restrictions
- MUST NOT modify: contracts/openapi.yaml, contracts/events/order_v1.json, packages/db/migrations/
- MUST NOT add co-author to commits
- Must use existing DB models (read-only)
- Must support OPENAI_API_BASE environment variable

## Success Metrics
- First token latency p50 ≤ 300ms local, p95 ≤ 800ms
- Token generation > 50 tokens/sec
- RAG relevance score > 0.8
- Tool call events properly logged
