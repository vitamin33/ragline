# Agent A: Core API & Data Layer

## Ownership

- **Exclusive**: services/api/, packages/db/, contracts/openapi.yaml
- **Shared**: packages/security/, packages/cache/
- **Read-only**: All other directories

## Deliverables

1. FastAPI application with JWT auth (tenant_id, roles, PKCE-ready)
2. SQLAlchemy 2.0 models and Alembic migrations
3. GET /v1/products/{id} with Redis cache-aside, TTL jitter, stampede lock
4. POST /v1/orders with Idempotency-Key (UPSERT pattern)
5. SSE endpoint GET /v1/orders/{id}/events and WebSocket /v1/ws
6. OpenAPI documentation with typed errors
7. Structured JSON logs with request_id, tenant_id

## Restrictions

- MUST NOT modify: contracts/events/\*.json, services/worker/, services/llm/
- MUST NOT add co-author to commits
- All DB migrations must be reversible
- Must expose outbox table for Agent B

## Success Metrics

- Cache hit ratio > 80%
- API p50 ≤ 40ms, p95 ≤ 120ms for cached requests
- 100% idempotency test coverage
- All endpoints documented in OpenAPI
