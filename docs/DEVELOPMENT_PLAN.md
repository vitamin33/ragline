# RAGline Development Plan

## Daily Sync Points
- 09:00: Contract review (any changes need approval from all agents)
- 14:00: Integration test sync
- 18:00: Merge coordination

## Merge Strategy
1. Contract changes merge FIRST (blocking for all agents)
2. Package changes merge SECOND (coordinate between affected agents)
3. Service changes merge LAST (independent per agent)

## Communication Protocol
- Use PR comments for cross-agent dependencies
- Tag issues with agent labels: agent-a, agent-b, agent-c
- Daily status updates in docs/DAILY_STATUS.md
- Block work with #BLOCKED tag when waiting for another agent

## Critical Integration Points
- Day 3: API ↔ Worker handoff via outbox table
- Day 4: Worker → Notifier → SSE/WS pipeline
- Day 5: LLM service contract finalization
- Day 6: Full stack integration test with RAG
- Day 7: Load testing with all components

## AI Enhancement Roadmap (Post v1.0.0 - UPDATED)

**REALITY CHECK**: Core platform is 90% complete - focus on advanced AI capabilities

### Phase 1: Advanced Function Calling (Days 8-10)
**Goal**: Close AI knowledge gaps for MLOps/LLM Specialist roles

**Building on existing sophisticated foundation:**
- ✅ **Tool registry system** already production-ready
- ✅ **3 working tools** (retrieve_menu, apply_promos, confirm)
- ✅ **RAG integration** fully functional

#### New Essential Tools (Build on Existing RAG)
- `search_knowledge_base` - Advanced semantic search across document types
- `analyze_conversation` - Sentiment analysis, intent classification, satisfaction scoring
- `generate_summary` - Multi-document summarization with custom styles
- `validate_input` - PII detection, content moderation, input sanitization

**Implementation advantage**: RAG pipeline, pgvector, and caching already working

#### Implementation Structure
```
services/llm/tools/
├── knowledge/
│   ├── search_knowledge_base.py
│   └── document_analyzer.py
├── analytics/
│   ├── analyze_conversation.py
│   └── sentiment_classifier.py
├── content/
│   ├── generate_summary.py
│   └── validate_input.py
└── registry.py  # Dynamic tool registration
```

### Phase 2: LLM Observability & Performance Metrics (Days 11-13)

**Building on existing infrastructure:**
- ✅ **Prometheus metrics configuration** already in Celery setup
- ✅ **Redis caching and performance tracking** ready
- ✅ **Structured logging** with request correlation

#### Core Metrics Implementation (Extend Existing)
```
packages/obs/              # NEW - build on existing structure
├── metrics.py           # Prometheus metrics
├── llm_monitoring.py    # LLM-specific tracking
├── tracing.py          # OpenTelemetry tracing
└── cost_tracker.py     # Token usage & cost tracking

services/llm/middleware/   # NEW - add to existing FastAPI
├── metrics_middleware.py  # FastAPI middleware
├── token_counter.py      # Real-time token counting
└── latency_tracker.py    # TTFT and p95 tracking
```

**Implementation advantage**: Observability structure exists, just needs LLM-specific metrics

#### Key Metrics to Track
- **TTFT (Time To First Token)**: < 300ms p50, < 500ms p95
- **Token Throughput**: > 50 tokens/sec sustained
- **Cost Per Request**: Track $0.001-0.01 range for optimization
- **Function Call Success Rate**: > 99% reliability
- **RAG Retrieval Performance**: < 50ms p95 similarity search

#### Grafana Dashboards
```
ops/grafana/dashboards/
├── llm_performance.json     # TTFT, throughput, latency
├── function_calling.json    # Tool execution metrics
├── rag_analytics.json       # Retrieval performance
└── cost_optimization.json   # Token usage & cost trends
```

### Phase 3: Prompt Governance System (Days 14-16)

#### Prompt Management Infrastructure
```
packages/prompts/
├── manager.py          # Version-controlled prompt management
├── validator.py        # Response validation (JSON, safety, accuracy)
├── testing.py          # Automated prompt testing framework
├── ab_testing.py       # A/B testing for prompt variations
└── approval_workflow.py # Git-based approval process

services/api/routers/
└── prompts.py          # Prompt management API endpoints

tests/prompt_tests/
├── regression_tests/    # Prevent prompt regressions
├── accuracy_tests/     # Test dataset validation
├── safety_tests/       # Content safety validation
└── json_validation/    # Response format validation
```

#### Git-Based Prompt Versioning
```
prompts/
├── system/
│   ├── chat_assistant.yml    # Main chat prompt v1.2.3
│   ├── function_caller.yml   # Tool calling prompt v1.1.0
│   └── safety_filter.yml     # Content moderation v2.0.1
├── tools/
│   ├── menu_retrieval.yml    # Menu search prompts
│   ├── conversation_analysis.yml
│   └── summarization.yml
└── templates/
    ├── greeting.yml          # Dynamic templates
    ├── error_handling.yml
    └── fallback_responses.yml
```

### Phase 4: Audio/Voice Integration (Days 17-19)

#### Voice-First Architecture
```
services/voice/
├── main.py                 # Voice service (Port 8002)
├── routers/
│   ├── speech_to_text.py  # STT endpoint
│   ├── text_to_speech.py  # TTS endpoint
│   └── voice_chat.py      # Real-time voice chat
├── processors/
│   ├── audio_processor.py # Audio preprocessing
│   ├── voice_activity.py  # VAD detection
│   └── noise_reduction.py # Audio enhancement
└── streaming/
    ├── websocket_audio.py # Real-time audio streams
    └── voice_pipeline.py  # STT→LLM→TTS pipeline

packages/audio/
├── codecs/
│   ├── opus_handler.py    # Opus codec support
│   ├── wav_processor.py   # WAV processing
│   └── webm_decoder.py    # Browser audio support
├── models/
│   ├── whisper_client.py  # OpenAI Whisper STT
│   ├── eleven_labs.py     # Premium TTS
│   └── local_tts.py       # Local TTS fallback
└── quality/
    ├── audio_metrics.py   # Audio quality metrics
    └── latency_optimizer.py # Real-time optimization
```

#### Real-Time Voice Features
- **WebRTC Integration**: Browser-native audio streaming
- **Voice Activity Detection**: Intelligent conversation breaks
- **Emotional Voice Synthesis**: Context-aware TTS tone
- **Multi-language Support**: Automatic language detection
- **Audio Quality Metrics**: Jitter, packet loss, latency tracking

### Phase 5: Production Hardening (Days 20-21)

#### Advanced Reliability Features
```
packages/reliability/
├── circuit_breaker.py     # Enhanced circuit breaker
├── rate_limiter.py        # Intelligent rate limiting
├── fallback_system.py     # Graceful degradation
└── health_monitor.py      # Advanced health checks

services/gateway/
├── main.py               # API Gateway (Port 8080)
├── load_balancer.py      # Intelligent load balancing
├── request_router.py     # Feature flag routing
└── auth_middleware.py    # Centralized authentication
```

#### Simple Test UI for Feature Validation

```
services/api/static/
├── index.html           # Main dashboard
├── chat.html           # LLM chat testing
├── voice.html          # Voice interaction testing
├── admin.html          # System monitoring
├── tools.html          # Function calling testing
├── prompts.html        # Prompt management UI
└── js/
    ├── api-client.js   # Core API interactions
    ├── websocket.js    # Real-time features
    ├── voice-client.js # WebRTC voice chat
    ├── tools-ui.js     # Function calling interface
    └── metrics-ui.js   # Performance monitoring
```

**UI Features:**
- **No framework dependencies** - Pure HTML/CSS/JS
- **Real-time testing** - SSE/WebSocket integration
- **Voice interaction** - WebRTC audio streaming
- **Function calling** - Test all AI tools interactively
- **Performance monitoring** - Live metrics dashboard
- **Multi-modal testing** - Text, voice, and structured data

## Naming Conventions
- Prometheus metrics prefix: ragline_
- Redis keys: ragline:{tenant_id}:{resource}:{id}
- Event topics: orders, chat_tools, voice_sessions
- Trace spans: ragline.{service}.{operation}
- Voice session IDs: voice_{uuid4}
- Prompt versions: {prompt_name}_v{major}.{minor}.{patch}
