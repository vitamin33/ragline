# RAGline Architecture

## System Overview

RAGline is a streaming-first, multi-tenant backend system demonstrating senior Python engineering skills with LLM/RAG orchestration capabilities.
┌─────────────────────────────────────────────────────────────┐
│ Clients │
│ (Web App, Mobile App, API Consumers) │
└─────────────┬───────────────────┬────────────────┬──────────┘
│ │ │
HTTP/WSS HTTP/SSE HTTP/REST
│ │ │
┌─────────────▼───────────────────▼────────────────▼──────────┐
│ Load Balancer │
└─────────────┬───────────────────┬────────────────┬──────────┘
│ │ │
┌─────▼──────┐ ┌────▼────┐ ┌────▼────┐
│ API │ │ LLM │ │ Worker │
│ Service │ │ Service │ │ Pool │
│ (8000) │ │ (8001) │ │ (Celery)│
└─────┬──────┘ └────┬────┘ └────┬────┘
│ │ │
└───────────────────┴────────────────┘
│
┌─────────────┴──────────────┐
│ │
┌───────▼────────┐ ┌────────▼────────┐
│ PostgreSQL │ │ Redis │
│ + pgvector │ │ Cache+Streams │
└────────────────┘ └─────────────────┘

## Project Structure

ragline/
├── services/ # Microservices
│ ├── api/ # Core REST API (Agent A)
│ │ ├── main.py # FastAPI application
│ │ ├── routers/ # API endpoints
│ │ │ ├── auth.py # Authentication endpoints
│ │ │ ├── products.py # Product CRUD
│ │ │ ├── orders.py # Order management
│ │ │ └── events.py # SSE/WebSocket endpoints
│ │ └── dependencies/ # FastAPI dependencies
│ │
│ ├── worker/ # Background workers (Agent B)
│ │ ├── celery_app.py # Celery configuration
│ │ ├── tasks/ # Task definitions
│ │ │ ├── outbox.py # Outbox consumer
│ │ │ ├── notifications.py
│ │ │ └── processing.py
│ │ └── config.py # Worker configuration
│ │
│ └── llm/ # LLM service (Agent C)
│ ├── main.py # FastAPI for LLM
│ ├── routers/
│ │ └── chat.py # Chat endpoints
│ ├── tools/ # LLM tools
│ │ ├── retrieve_menu.py
│ │ ├── apply_promos.py
│ │ └── confirm.py
│ └── streaming.py # SSE/WS streaming
│
├── packages/ # Shared packages
│ ├── db/ # Database (Agent A)
│ │ ├── models.py # SQLAlchemy models
│ │ ├── database.py # Connection management
│ │ └── alembic/ # Migrations
│ │
│ ├── cache/ # Caching (Agent A)
│ │ ├── redis_cache.py
│ │ └── patterns.py # Cache-aside, etc.
│ │
│ ├── security/ # Auth & Security (Agent A)
│ │ ├── jwt.py # JWT handling
│ │ ├── auth.py # Authentication
│ │ └── rbac.py # Role-based access
│ │
│ ├── orchestrator/ # Event orchestration (Agent B)
│ │ ├── outbox.py # Outbox pattern
│ │ ├── streams.py # Redis streams
│ │ ├── retry.py # Retry logic
│ │ └── circuit_breaker.py
│ │
│ ├── rag/ # RAG implementation (Agent C)
│ │ ├── embeddings.py # Vector embeddings
│ │ ├── llm_client.py # OpenAI/local models
│ │ ├── retrieval.py # Similarity search
│ │ └── ingestion.py # Data ingestion
│ │
│ └── obs/ # Observability (Shared)
│ ├── metrics.py # Prometheus metrics
│ ├── tracing.py # OpenTelemetry
│ └── logging.py # Structured logging
│
├── contracts/ # API & Event contracts
│ ├── openapi.yaml # REST API spec (Agent A)
│ └── events/
│ ├── order_v1.json # Order events (Agent B)
│ └── chat_tool_v1.json # Chat events (Agent C)
│
├── tests/ # Test suites
│ ├── unit/
│ ├── integration/
│ ├── concurrency/
│ └── dialogue/
│
├── ops/ # Operations
│ ├── docker-compose.yml
│ ├── grafana/ # Dashboards
│ └── k6/ # Load tests
│
└── docs/ # Documentation
├── ARCHITECTURE.md # This file
├── DAILY_STATUS.md # Daily progress
├── SLOs.md # Service level objectives
└── SECURITY.md # Security practices

## Core Components

### 1. API Service (Port 8000)

- **Owner**: Agent A
- **Tech**: FastAPI, async Python
- **Responsibilities**:
  - JWT authentication with tenant isolation
  - Product CRUD with caching
  - Order creation with idempotency
  - SSE/WebSocket for real-time updates

### 2. Worker Service

- **Owner**: Agent B
- **Tech**: Celery, Redis Streams
- **Responsibilities**:
  - Outbox pattern implementation
  - Event streaming and fan-out
  - Retry with exponential backoff
  - Circuit breaker for external services
  - Dead Letter Queue management

### 3. LLM Service (Port 8001)

- **Owner**: Agent C
- **Tech**: FastAPI, OpenAI API, pgvector
- **Responsibilities**:
  - Streaming chat responses
  - Tool calling (retrieve_menu, apply_promos, confirm)
  - RAG over product catalog
  - Local model support via OPENAI_API_BASE

## Data Flow Patterns

### 1. Synchronous Request Flow

Client → API → Database → Cache → Response

### 2. Asynchronous Event Flow

API → Outbox → Worker → Redis Stream → Notifier → SSE/WS → Client

### 3. LLM Tool Calling Flow

Client → LLM Service → Tool Execution → RAG Retrieval → Response Stream

## Database Schema

### Core Tables

- `tenants` - Multi-tenant isolation
- `users` - Authentication and authorization
- `products` - Product catalog
- `orders` - Order management
- `order_items` - Order line items
- `outbox` - Event sourcing
- `jobs` - Background job tracking

### Indexes

- `idx_users_tenant_email` - Unique per tenant
- `idx_products_tenant_sku` - Product lookup
- `idx_orders_tenant_idempotency` - Idempotency
- `idx_outbox_unprocessed` - Outbox polling

## Caching Strategy

### Cache Patterns

- **Cache-aside**: Read through cache for products
- **Write-through**: Update cache on writes
- **TTL with jitter**: Prevent thundering herd

### Redis Key Patterns

ragline:{tenant_id}:cache:product:{id}
ragline:{tenant_id}:lock:{resource}:{id}
ragline:stream:orders
ragline:dlq:orders

## Event Architecture

### Event Types

- `order_created` - New order placed
- `order_updated` - Order status changed
- `order_cancelled` - Order cancelled
- `tool_call` - LLM tool execution

### Stream Topics

- `orders` - Order lifecycle events
- `notifications` - User notifications
- `chat_tools` - LLM tool executions

## Security

### Authentication

- JWT with claims: `tenant_id`, `user_id`, `roles[]`
- Token expiry: 30 minutes
- Refresh token support

### Authorization

- Tenant isolation at database level
- Role-based access control (RBAC)
- Rate limiting per tenant

### API Security

- CORS configuration
- Request validation with Pydantic
- SQL injection prevention via SQLAlchemy
- XSS protection headers

## Observability

### Metrics (Prometheus)

All metrics use `ragline_` prefix:

- `ragline_api_request_duration_seconds`
- `ragline_cache_hit_ratio`
- `ragline_worker_task_duration_seconds`
- `ragline_outbox_lag_seconds`
- `ragline_stream_lag_seconds`
- `ragline_llm_first_token_ms`
- `ragline_llm_tokens_total`

### Tracing (OpenTelemetry)

- Distributed tracing across services
- Span attributes: `tenant_id`, `user_id`, `request_id`
- Trace visualization in Jaeger

### Logging

- Structured JSON logging
- Correlation IDs across services
- PII-safe logging filters

## Performance Targets

### API Service

- p50 latency: < 40ms (cached)
- p95 latency: < 120ms
- Cache hit ratio: > 80%

### Worker Service

- Outbox polling: 100ms interval
- Stream lag: < 100ms p95
- DLQ recovery: > 99%

### LLM Service

- First token: < 300ms p50
- Token generation: > 50 tokens/sec
- RAG retrieval: < 50ms

## Deployment

### Local Development

```bash
just up     # Start dependencies
just dev    # Run all services
just test   # Run tests
just k6     # Load testing
Production Considerations

Horizontal scaling for API and Worker services
Connection pooling for database
Redis cluster for high availability
Prometheus federation for metrics
Log aggregation with ELK/Loki

Technology Stack
Core

Python 3.11+
FastAPI
SQLAlchemy 2.0
Celery
Redis

Database

PostgreSQL 16
pgvector extension
Alembic migrations

LLM/RAG

OpenAI API
Ollama (local models)
Sentence Transformers
pgvector for embeddings

Observability

Prometheus
Grafana
OpenTelemetry
Jaeger

Testing

pytest
httpx
k6 (load testing)
EOF
```
