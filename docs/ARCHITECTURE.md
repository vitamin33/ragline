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
│ │ ├── dependencies/ # FastAPI dependencies
│ │ └── static/ # Test UI (Agent A)
│ │   ├── index.html # Main test interface
│ │   ├── chat.html # Chat testing UI
│ │   ├── voice.html # Voice testing UI (Days 17-19)
│ │   ├── admin.html # System monitoring UI
│ │   └── js/
│ │     ├── api-client.js # API interaction
│ │     ├── websocket.js # Real-time features
│ │     └── voice-client.js # Voice features
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

### 4. Voice Service (Port 8002) - *Future Enhancement*

- **Owner**: Agent C (Extension)
- **Tech**: FastAPI, OpenAI Whisper, WebRTC, Opus codec
- **Responsibilities**:
  - Speech-to-text processing (Whisper integration)
  - Text-to-speech synthesis (ElevenLabs/Local TTS)
  - Real-time audio streaming via WebSocket
  - Voice activity detection and audio enhancement
  - Multi-language support and emotional synthesis

### 5. API Gateway (Port 8080) - *Future Enhancement*

- **Owner**: Shared (All Agents)
- **Tech**: FastAPI, intelligent load balancing
- **Responsibilities**:
  - Unified API entry point
  - Request routing and feature flags
  - Centralized authentication and rate limiting
  - Circuit breaker coordination

## Data Flow Patterns

### 1. Synchronous Request Flow

Client → API → Database → Cache → Response

### 2. Asynchronous Event Flow

API → Outbox → Worker → Redis Stream → Notifier → SSE/WS → Client

### 3. LLM Tool Calling Flow

Client → LLM Service → Tool Execution → RAG Retrieval → Response Stream

### 4. Voice Interaction Flow - *Future Enhancement*

Client → Voice Service (STT) → LLM Service → Tool Execution → Voice Service (TTS) → Audio Stream → Client

### 5. Advanced Function Calling Flow - *Future Enhancement*

Client → LLM Service → Dynamic Tool Registry → External APIs → Caching Layer → Response Stream

### 6. Prompt Governance Flow - *Future Enhancement*

Prompt Request → Version Manager → A/B Testing → Validation → Git Repository → LLM Service

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

#### Core Platform Metrics
- `ragline_api_request_duration_seconds`
- `ragline_cache_hit_ratio`
- `ragline_worker_task_duration_seconds`
- `ragline_outbox_lag_seconds`
- `ragline_stream_lag_seconds`

#### LLM Performance Metrics - *Enhanced*
- `ragline_llm_first_token_ms` - Time to first token (TTFT)
- `ragline_llm_tokens_total` - Total token count
- `ragline_llm_tokens_per_second` - Token throughput
- `ragline_llm_request_cost_usd` - Cost per request tracking
- `ragline_llm_p95_latency_seconds` - 95th percentile latency

#### Function Calling Metrics - *Future Enhancement*
- `ragline_tool_execution_duration_seconds`
- `ragline_tool_success_rate`
- `ragline_tool_cache_hit_ratio`
- `ragline_rag_retrieval_latency_ms`

#### Voice Service Metrics - *Future Enhancement*
- `ragline_voice_stt_latency_ms`
- `ragline_voice_tts_latency_ms`
- `ragline_voice_session_duration_seconds`
- `ragline_voice_audio_quality_score`

#### Prompt Governance Metrics - *Future Enhancement*
- `ragline_prompt_version_usage_total`
- `ragline_prompt_ab_test_conversion_rate`
- `ragline_prompt_validation_failures_total`

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

### LLM Service - *Enhanced Targets*

- **TTFT (Time To First Token)**: < 300ms p50, < 500ms p95
- **Token Throughput**: > 50 tokens/sec sustained
- **Cost Per Request**: $0.001-0.01 range optimization
- **Function Call Success Rate**: > 99% reliability
- **RAG Retrieval**: < 50ms p95 similarity search

### Voice Service - *Future Targets*

- **Speech-to-Text Latency**: < 200ms p95
- **Text-to-Speech Latency**: < 400ms p95
- **End-to-End Voice**: < 800ms p95 (STT→LLM→TTS)
- **Audio Quality Score**: > 4.0/5.0 MOS rating
- **Concurrent Voice Sessions**: 100+ simultaneous

### Advanced Function Calling - *Future Targets*

- **Tool Execution**: < 200ms p95 (cached)
- **External API Integration**: < 500ms p95
- **Semantic Search Accuracy**: > 0.85 relevance score
- **Content Validation**: < 100ms p95 processing

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
