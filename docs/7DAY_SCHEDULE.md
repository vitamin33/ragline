# RAGline 7-Day Implementation Schedule

## Day 1 - Bootstrap & Contracts
- **All Agents**: Setup development environment
- **09:00**: Define all contracts together
- **Agent A**: FastAPI bootstrap, JWT setup
- **Agent B**: Celery configuration
- **Agent C**: LLM service structure
- **18:00**: Commit contracts to main

## Day 2 - Core Features
- **Agent A**: Products API with caching
- **Agent B**: Outbox consumer design
- **Agent C**: Chat endpoint structure
- **Integration**: Agree on Redis key patterns

## Day 3 - Data Flow
- **Agent A**: Order creation with idempotency
- **Agent B**: Outbox → Streams pipeline
- **Agent C**: Tool calling framework
- **Critical**: Outbox table handoff (A→B)

## Day 4 - Event System
- **Agent A**: SSE/WS endpoints
- **Agent B**: Notifier implementation
- **Agent C**: Streaming response
- **Test**: End-to-end event flow

## Day 5 - Advanced Features
- **Agent A**: Rate limiting, observability
- **Agent B**: Circuit breaker, DLQ
- **Agent C**: RAG implementation
- **Metrics**: First dashboard iteration

## Day 6 - Integration & Polish
- **All**: Integration testing
- **Agent A**: Performance optimization
- **Agent B**: Load testing SSE
- **Agent C**: Local model testing
- **Docs**: Update ARCHITECTURE.md

## Day 7 - Demo & Documentation
- **Morning**: k6 load tests
- **Afternoon**: Create demo videos
- **Evening**: Screenshots, final docs
- **Ship**: Merge to main, tag v1.0.0
