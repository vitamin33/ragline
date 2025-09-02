# Agent B: Reliability & Events + Infrastructure Operations

## Ownership

### Core Platform (Days 1-7)
- **Exclusive**: services/worker/, packages/orchestrator/, contracts/events/order_v1.json
- **Read-only**: packages/db/, services/api/

### AI Enhancement Phase (Days 8-21)
- **Extended**: packages/reliability/ (Circuit breakers, rate limiters, graceful degradation)
- **New Ownership**: Event processing for all AI features (tool execution, prompt changes, voice sessions)
- **Monitoring**: Complete observability infrastructure and alerting

## Core Deliverables (Days 1-7)

1. Celery workers with IO pool and ProcessPool
2. Outbox pattern: writer post-commit, consumer to Redis Streams
3. Redis Streams producer/consumer for "orders" topic
4. Notifier fan-out to SSE and WS with backpressure handling
5. Retry mechanism with jitter, circuit breaker for external adapter
6. Dead Letter Queue implementation with requeue capability
7. Prometheus metrics: stream lag, consumer lag, retries, DLQ size

## AI Enhancement Deliverables (Days 8-21)

### Phase 1: Advanced Function Calling (Days 8-10)
- Tool execution event tracking and metrics collection
- Tool result caching with intelligent invalidation
- External API circuit breakers and retry mechanisms
- Tool performance metrics and alerting system

### Phase 2: LLM Observability (Days 11-13)
- Stream metrics and worker observability with Prometheus export
- RAG retrieval performance metrics and stream lag monitoring
- Event tracing with worker span creation and alerting rules
- Complete observability pipeline for all AI operations

### Phase 3: Prompt Governance (Days 14-16)
- Prompt deployment pipeline with change event tracking
- Prompt test execution pipeline with result aggregation and CI/CD
- A/B test event streaming with analytics aggregation and alerts
- Automated prompt deployment and rollback mechanisms

### Phase 4: Voice Integration (Days 17-19)
- Voice session events and audio processing queues
- Audio processing pipeline with voice activity detection and stream buffering
- Audio quality metrics with latency optimization and concurrent session handling
- Real-time audio stream management and quality monitoring

### Phase 5: Production Hardening (Days 20-21)
- **Enhanced Reliability**: Advanced circuit breakers, intelligent rate limiting, graceful degradation
- Monitoring playbooks with comprehensive alerting configuration
- Scaling guides and auto-scaling implementations
- Production-grade reliability patterns across all services

## Enhanced Success Metrics

### Core Platform
- Stream lag < 100ms p95
- DLQ recovery rate > 99%
- 5k concurrent SSE connections stable
- Circuit breaker tested with failure scenarios

### AI Enhancement Phase
- Tool execution event processing < 50ms p95
- Audio processing pipeline latency < 200ms p95
- Prompt deployment pipeline success rate > 99.9%
- Voice session concurrency > 100 simultaneous sessions
- Complete observability coverage with < 1 minute alert resolution
- System reliability > 99.95% uptime across all AI features

## Enhanced Event Schemas

### New Event Types (Days 8-21)
- `tool_executed` - Function calling completion events
- `prompt_deployed` - Prompt version changes
- `voice_session_started/ended` - Voice interaction lifecycle
- `ab_test_assignment` - A/B testing events
- `audio_quality_alert` - Voice quality monitoring

## Restrictions

- MUST NOT modify: contracts/openapi.yaml, packages/db/migrations/, services/llm/
- MUST NOT add co-author to commits
- Must coordinate with Agent A for DB read operations
- Must use existing outbox table structure
- All new event schemas must be backward compatible
