# RAGline RAG Architecture Decision

## Vector Database Decision: pgvector vs Qdrant

### Decision: **pgvector** ✅

**Rationale:**
- **Simplicity**: Leverages existing PostgreSQL infrastructure
- **Integration**: Already using PostgreSQL for core data
- **Maintenance**: Single database system to manage
- **Performance**: Sufficient for restaurant menu/order context
- **ACID Compliance**: Transactional consistency with business data
- **Cost**: No additional vector database service needed

### pgvector vs Qdrant Comparison:

| Factor | pgvector | Qdrant |
|--------|----------|--------|
| Setup Complexity | Low (PostgreSQL extension) | Medium (Separate service) |
| Performance | Good (< 1M vectors) | Excellent (> 1M vectors) |
| Integration | Seamless (same DB) | Requires API calls |
| Maintenance | Single system | Two systems |
| Features | Basic but sufficient | Advanced filtering |
| Cost | Lower | Higher |
| RAGline Scale | Perfect fit | Overkill |

**For RAGline's use case** (restaurant menus, order context, customer data):
- Vector count: < 100k documents
- Query frequency: Moderate
- Latency requirements: < 50ms p95
- Integration priority: High

**pgvector is the optimal choice.**

## RAG Architecture Overview

```
User Query
    ↓
Query Processing & Intent Detection
    ↓
Embedding Generation (OpenAI/SentenceTransformers)
    ↓
Vector Search (pgvector)
    ↓
Context Retrieval & Ranking
    ↓
Prompt Enhancement
    ↓
LLM Generation (OpenAI)
    ↓
Response with Context
```

## Data Sources for RAG

1. **Menu Items** - Dishes, ingredients, prices, dietary info
2. **Customer Preferences** - Previous orders, dietary restrictions
3. **Order History** - Past orders for personalization
4. **Restaurant Policies** - Hours, delivery areas, promotions
5. **FAQ Content** - Common questions and answers

## Chunking Strategy

### 1. Menu Items (Structured)
- **Chunk Size**: Per menu item (natural boundary)
- **Content**: Name + Description + Ingredients + Price + Category
- **Metadata**: Category, dietary_info, price_range, availability

### 2. Policies & FAQ (Unstructured)
- **Chunk Size**: 256-512 tokens
- **Overlap**: 50 tokens
- **Boundaries**: Sentence-aware splitting
- **Metadata**: Document type, section, last_updated

### 3. Customer Data (Contextual)
- **Chunk Size**: Per interaction/order
- **Content**: Order details + preferences + feedback
- **Metadata**: Customer_id, order_date, satisfaction_score

## Vector Dimensions

- **OpenAI text-embedding-3-small**: 1536 dimensions
- **SentenceTransformers alternative**: 384-768 dimensions
- **Choice**: OpenAI for consistency with LLM model

## Retrieval Strategy

1. **Hybrid Search**: Vector similarity + keyword matching
2. **Filtering**: Category, price, dietary restrictions
3. **Re-ranking**: Business rules (availability, popularity)
4. **Top-K**: 5-10 most relevant chunks
5. **Context Window**: ~2000 tokens for LLM context

## Implementation Plan

### Phase 1: Core RAG (Current)
- pgvector setup
- Embedding generation
- Basic vector search
- Menu item ingestion

### Phase 2: Enhanced RAG
- Hybrid search (vector + keyword)
- Customer context integration
- Advanced filtering and ranking

### Phase 3: Personalization
- Customer preference learning
- Order history integration
- Dynamic re-ranking based on user behavior

## Performance Targets

- **Embedding Generation**: < 100ms
- **Vector Search**: < 30ms p95
- **Total RAG Latency**: < 200ms p95
- **Relevance**: > 80% user satisfaction
- **Cache Hit Rate**: > 60% for common queries
