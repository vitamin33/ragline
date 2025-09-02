# Agent C: LLM & RAG + Advanced AI Features

## Ownership

### Core Platform (Days 1-7)
- **Exclusive**: services/llm/, packages/rag/, contracts/events/chat_tool_v1.json
- **Shared**: packages/obs/
- **Read-only**: All other directories

### AI Enhancement Phase (Days 8-21)
- **Extended**: services/voice/ (Voice Service - Port 8002)
- **New Ownership**: packages/prompts/ (Prompt governance), packages/tools/ (Advanced function calling)
- **AI Infrastructure**: Complete LLM observability, cost optimization, model management

## Core Deliverables (Days 1-7)

1. POST /v1/chat with SSE/WS streaming
2. Tool-using flow: retrieve_menu → apply_promos → confirm
3. RAG over menu data via pgvector or Qdrant
4. Local model support via OpenAI-compatible endpoint (Ollama/vLLM)
5. Metrics: ragline_llm_first_token_ms, ragline_llm_latency_ms, ragline_llm_tokens_total
6. Voice gateway with ASR (foundation for Days 17-19)

## AI Enhancement Deliverables (Days 8-21)

### Phase 1: Advanced Function Calling (Days 8-10)
- **Dynamic tool registry** with semantic search and hot-swapping
- **Essential AI Tools**:
  - `search_knowledge_base` - Advanced semantic search across document types
  - `analyze_conversation` - Sentiment analysis, intent classification, satisfaction scoring
  - `generate_summary` - Multi-document summarization with custom styles
  - `validate_input` - PII detection, content moderation, input sanitization
- **Tool optimization**: Caching, semantic deduplication, performance monitoring

### Phase 2: LLM Observability (Days 11-13)
- **Complete `packages/obs/` implementation**: metrics.py, llm_monitoring.py, tracing.py
- **Production LLM Metrics**:
  - TTFT tracking with real-time optimization
  - Token throughput monitoring and cost tracking
  - Function call success rate and model performance comparison
  - Token usage optimization with cost analysis
- **OpenTelemetry integration** with distributed tracing completion

### Phase 3: Prompt Governance (Days 14-16)
- **Git-based prompt versioning** with automated deployment
- **Enterprise prompt management**:
  - Automated testing framework with response validation
  - Regression test suite for prompt quality assurance
  - A/B testing framework with prompt performance analytics
- **Production prompt pipeline** with approval workflows and rollback capabilities

### Phase 4: Voice Integration (Days 17-19)
- **Voice Service (Port 8002)** - Complete real-time voice interaction system
- **Speech processing pipeline**:
  - OpenAI Whisper STT with optimization for low latency
  - ElevenLabs + Local TTS with emotional synthesis
  - Voice → LLM → TTS pipeline with < 800ms end-to-end latency
- **Advanced voice features**:
  - Multi-language support with automatic detection
  - Voice cloning and emotional voice synthesis
  - Multi-model TTS support with quality optimization

### Phase 5: Production Hardening (Days 20-21)
- **Model performance optimization** with multi-model support and intelligent routing
- **Enterprise AI features**: Fallback systems, cost optimization, scaling automation
- **Complete AI documentation**: Model deployment guides, performance tuning, cost optimization
- **Production AI readiness**: Model versioning, A/B testing, performance monitoring

## Enhanced Success Metrics

### Core Platform
- First token latency p50 ≤ 300ms local, p95 ≤ 800ms
- Token generation > 50 tokens/sec
- RAG relevance score > 0.8
- Tool call events properly logged

### AI Enhancement Phase

#### Advanced Function Calling
- Tool execution latency < 200ms p95 (cached)
- Semantic search accuracy > 0.85 relevance score
- Content validation processing < 100ms p95
- PII detection accuracy > 99.5%

#### LLM Observability
- **TTFT**: < 300ms p50, < 500ms p95
- **Token throughput**: > 50 tokens/sec sustained
- **Cost optimization**: $0.001-0.01 per request tracking
- **Function call success rate**: > 99% reliability

#### Voice Integration
- **Speech-to-Text latency**: < 200ms p95
- **Text-to-Speech latency**: < 400ms p95
- **End-to-end voice interaction**: < 800ms p95
- **Audio quality**: > 4.0/5.0 MOS rating
- **Concurrent voice sessions**: 100+ simultaneous

#### Prompt Governance
- Prompt deployment success rate > 99.9%
- A/B test statistical significance within 24 hours
- Response validation accuracy > 95%
- Zero prompt regression incidents

## Advanced Tool Capabilities

### Semantic AI Tools (Days 8-10)
- **Multi-document search** across PDFs, markdown, code, structured data
- **Conversation analytics** with sentiment trends and user satisfaction prediction
- **Content generation** with style adaptation and quality scoring
- **Safety systems** with real-time content moderation and PII protection

### Model Management (Days 11-21)
- **Multi-provider support**: OpenAI, Anthropic, local models (Ollama/vLLM)
- **Intelligent routing**: Cost-based, latency-based, quality-based model selection
- **Cost optimization**: Token usage tracking, model efficiency analysis
- **Performance monitoring**: Real-time model comparison and optimization

## Restrictions

- MUST NOT modify: contracts/openapi.yaml, contracts/events/order_v1.json, packages/db/migrations/
- MUST NOT add co-author to commits
- Must use existing DB models (read-only)
- Must support OPENAI_API_BASE environment variable
- Voice service must not conflict with existing LLM service ports
- All AI features must maintain backward compatibility with core platform
