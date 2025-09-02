# Agent A: Core API & Data Layer + Frontend Integration

## Ownership

### Core Platform (Days 1-7)
- **Exclusive**: services/api/, packages/db/, contracts/openapi.yaml
- **Shared**: packages/security/, packages/cache/
- **Read-only**: All other directories

### AI Enhancement Phase (Days 8-21)
- **Extended**: services/gateway/ (API Gateway - Port 8080)
- **New Shared**: packages/validation/ (Content validation)
- **New Endpoints**: Tool execution APIs, Prompt management, Voice session management

## Core Deliverables (Days 1-7)

1. FastAPI application with JWT auth (tenant_id, roles, PKCE-ready)
2. SQLAlchemy 2.0 models and Alembic migrations
3. GET /v1/products/{id} with Redis cache-aside, TTL jitter, stampede lock
4. POST /v1/orders with Idempotency-Key (UPSERT pattern)
5. SSE endpoint GET /v1/orders/{id}/events and WebSocket /v1/ws
6. OpenAPI documentation with typed errors
7. Structured JSON logs with request_id, tenant_id
8. **Simple Test UI** (served at `/static/`):
   - Basic HTML interface for testing all API endpoints
   - Real-time events display (SSE/WebSocket)
   - Product/order management forms
   - System status monitoring

## AI Enhancement Deliverables (Days 8-21)

### Phase 1: Advanced Function Calling (Days 8-10)
- Tool execution API endpoints with validation middleware
- PII detection API and content moderation endpoints
- Tool execution rate limiting and quota management
- Tool result validation and error handling

### Phase 2: LLM Observability (Days 11-13)
- API metrics middleware with request tracking
- Cost allocation and user session tracking
- P95 latency middleware and performance monitoring
- Distributed tracing correlation and request flow tracking

### Phase 3: Prompt Governance (Days 14-16)
- Prompt management API endpoints with version control integration
- Prompt testing API with validation endpoints and approval workflow
- A/B test configuration API with user assignment and results tracking
- Prompt deployment and governance endpoints

### Phase 4: Voice Integration (Days 17-19)
- Voice session API with WebRTC signaling
- Audio upload endpoints and session management
- WebSocket audio streaming with quality monitoring
- Multi-language support API and voice preference management
- **Voice Test UI**: Real-time voice chat interface with audio controls

### Phase 5: Production Hardening (Days 20-21)
- **API Gateway (Port 8080)**: Intelligent routing, centralized auth, load balancing
- API documentation and deployment guides
- Security hardening and enterprise-grade authentication
- Complete OpenAPI documentation for all enhanced endpoints

## Enhanced Success Metrics

### Core Platform
- Cache hit ratio > 80%
- API p50 ≤ 40ms, p95 ≤ 120ms for cached requests
- 100% idempotency test coverage
- All endpoints documented in OpenAPI

### AI Enhancement Phase
- Tool execution API p95 ≤ 200ms
- Content validation processing < 100ms p95
- Voice session API latency < 50ms p95
- API Gateway routing efficiency > 99%
- Complete observability instrumentation across all endpoints

## Restrictions

- MUST NOT modify: contracts/events/\*.json, services/worker/, services/llm/
- MUST NOT add co-author to commits
- All DB migrations must be reversible
- Must expose outbox table for Agent B
- API Gateway must not interfere with existing service boundaries
