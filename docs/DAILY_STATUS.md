# RAGline Daily Status

## Current Sprint: Day 1 - 2025-08-24

### 🎯 Today's Goals

- Set up development environment for all agents
- Define and validate all contracts (OpenAPI, events)
- Bootstrap basic structure for each service
- Establish integration patterns

---

## 📋 Agent A (Core API & Data)

**Branch:** `feat/core-api`
**Focus:** FastAPI, SQLAlchemy, JWT, Redis caching

### Tasks

- [ ] Bootstrap FastAPI application structure
  - [ ] Create `services/api/main.py` with app initialization
  - [ ] Set up `services/api/routers/` directory structure
  - [ ] Configure CORS, middleware, exception handlers
- [ ] Implement JWT authentication
  - [ ] Create `packages/security/jwt.py` with token generation
  - [ ] Add `packages/security/auth.py` with login/verify logic
  - [ ] Include tenant_id and roles in JWT claims
- [x] Define SQLAlchemy 2.0 models
  - [ ] Create `packages/db/models.py` with base models
  - [ ] Define Tenant, User, Product, Order, Outbox tables
  - [ ] Set up `packages/db/database.py` with async session
- [ ] Initialize Alembic
  - [ ] Run `alembic init` in packages/db/
  - [ ] Create initial migration with all tables
  - [ ] Test upgrade/downgrade commands

**Progress:** 1/4 main tasks (25%)
**Blockers:** None
**Notes:** Outbox table schema must be shared with Agent B by 14:00

---

## 📋 Agent B (Reliability & Events)

**Branch:** `feat/reliability`
**Focus:** Celery, Redis Streams, Event orchestration

### Tasks

- [ ] Setup Celery configuration
  - [ ] Create `services/worker/celery_app.py` with app config
  - [ ] Configure IO pool and Process pool in `services/worker/config.py`
  - [ ] Add basic health check task
- [ ] Design outbox consumer
  - [ ] Create `packages/orchestrator/outbox.py` with consumer logic
  - [ ] Implement polling mechanism (100ms interval)
  - [ ] Add processed_at update logic
- [ ] Implement Redis streams
  - [ ] Create `packages/orchestrator/redis_client.py` with connection pool
  - [ ] Add retry logic with exponential backoff
  - [ ] Implement stream producer for orders topic
- [ ] Define event schema
  - [ ] Validate order_v1.json structure
  - [ ] Create Pydantic models for events
  - [ ] Add event serialization/deserialization

**Progress:** 0/4 main tasks (0%)
**Blockers:** None
**Notes:** Must coordinate Redis key patterns with Agent A

---

## 📋 Agent C (LLM & RAG)

**Branch:** `feat/llm`
**Focus:** LLM orchestration, RAG, Streaming

### Tasks

- [ ] Setup LLM service structure
  - [ ] Create `services/llm/main.py` with FastAPI app
  - [ ] Add `services/llm/routers/chat.py` for chat endpoint
  - [ ] Configure SSE/WebSocket support
- [ ] Configure LLM client
  - [ ] Create `packages/rag/llm_client.py` with OpenAI client
  - [ ] Add OPENAI_API_BASE override for local models
  - [ ] Implement retry logic and timeout handling
- [ ] Design tool system
  - [ ] Validate chat_tool_v1.json schema
  - [ ] Create `services/llm/tools/` directory structure
  - [ ] Define tool interfaces (retrieve_menu, apply_promos, confirm)
- [ ] Plan RAG architecture
  - [ ] Decision: pgvector vs Qdrant (recommend: pgvector for simplicity)
  - [ ] Create `packages/rag/embeddings.py` for vector operations
  - [ ] Design document chunking strategy

**Progress:** 0/4 main tasks (0%)
**Blockers:** None
**Notes:** Using pgvector (already in Postgres) instead of separate Qdrant

---

## 🔄 Integration Checkpoints

| Time  | Checkpoint      | Status     | Details                              |
| ----- | --------------- | ---------- | ------------------------------------ |
| 09:00 | Contract Review | ⏳ Pending | All agents review contracts together |
| 11:00 | Data Model Sync | ⏳ Pending | Agent A shares SQLAlchemy models     |
| 14:00 | Outbox Handoff  | ✅ Done    | Agent A → Agent B schema sharing     |
| 16:00 | Redis Patterns  | ⏳ Pending | Agree on key naming conventions      |
| 18:00 | Daily Merge     | ⏳ Pending | Push all branches, update status     |

---

## 📊 Overall Progress

**Total Tasks:** 0/12 completed (0%)
**On Track:** ✅ Yes
**Risk Level:** 🟢 Low

---

## 🚧 Active Blockers

None currently.

---

## 📝 Decisions Made

1. **Database:** PostgreSQL with pgvector extension (no separate Qdrant)
2. **Auth:** JWT with tenant_id, user_id, roles[] claims
3. **Events:** Redis Streams for event bus
4. **Caching:** Redis with cache-aside pattern
5. **API:** FastAPI with async/await throughout

---

## 🔮 Tomorrow's Priority (Day 2)

- **Agent A:** Product CRUD with Redis caching, idempotency implementation
- **Agent B:** Outbox consumer running, SSE/WS notifier basics
- **Agent C:** Streaming chat endpoint, basic RAG ingestion

---

## 📌 Important Notes

- All agents must install requirements.txt from main repo
- No "Co-authored-with" in any commits
- Follow commit format: `feat(scope): description`
- Contracts are immutable once agreed upon

---

_Last updated: 2025-08-24 20:18:45_
_Next sync: 2025-08-25 09:00_
