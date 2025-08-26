# RAGline Development Tasks

# Start all infrastructure services
up:
    docker-compose -f ops/docker-compose.yml up -d
    @echo "Waiting for services to be ready..."
    @sleep 5
    @echo "Services running:"
    @echo "  PostgreSQL: localhost:5432"
    @echo "  Redis: localhost:6379"
    @echo "  Prometheus: http://localhost:9090"
    @echo "  Grafana: http://localhost:3000 (admin/admin)"
    @echo "  Jaeger: http://localhost:16686"
    @echo "  Qdrant: http://localhost:6333"

# Stop all services
down:
    docker-compose -f ops/docker-compose.yml down

# Run all services in development mode
dev:
    #!/usr/bin/env bash
    set -e
    echo "Starting RAGline services..."
    (cd services/api && uvicorn main:app --reload --port 8000) &
    (cd services/worker && PYTHONPATH=/Users/vitaliiserbyn/development/ragline celery -A celery_app worker --loglevel=info) &
    (cd services/llm && uvicorn main:app --reload --port 8001) &
    wait

# Seed database with test data
ingest:
    python scripts/seed_data.py

# Demo: Create order with idempotency
demo-order:
    @echo "Creating order with idempotency test..."
    curl -X POST http://localhost:8000/v1/orders \
      -H "Content-Type: application/json" \
      -H "Idempotency-Key: test-order-123" \
      -d '{"items": [{"sku": "PROD-001", "quantity": 2}]}'
    @echo "\nRetrying with same Idempotency-Key..."
    curl -X POST http://localhost:8000/v1/orders \
      -H "Content-Type: application/json" \
      -H "Idempotency-Key: test-order-123" \
      -d '{"items": [{"sku": "PROD-001", "quantity": 2}]}'

# Demo: Chat with RAG and tools
demo-chat:
    @echo "Testing chat with tools..."
    curl -X POST http://localhost:8001/v1/chat \
      -H "Content-Type: application/json" \
      -d '{"messages": [{"role": "user", "content": "Show me the menu and apply any promos"}]}'

# Run k6 load tests
k6:
    k6 run ops/k6/load_test.js

# Run tests for specific agent
test-agent agent:
    #!/usr/bin/env bash
    case {{agent}} in
        a) cd ../ragline-a && pytest tests/ -v ;;
        b) cd ../ragline-b && pytest tests/ -v ;;
        c) cd ../ragline-c && pytest tests/ -v ;;
        *) echo "Invalid agent. Use: a, b, or c" ;;
    esac

# Check which agent owns a file
check-owner file:
    @python scripts/check_ownership.py {{file}}

# Sync all worktrees with main
sync-all:
    @echo "Syncing all worktrees..."
    @git fetch origin
    @cd ../ragline-a && git fetch origin && git rebase origin/main
    @cd ../ragline-b && git fetch origin && git rebase origin/main
    @cd ../ragline-c && git fetch origin && git rebase origin/main
    @echo "All worktrees synced"
