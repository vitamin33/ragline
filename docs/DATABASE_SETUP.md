# RAGline Database Setup Guide

## Overview

To complete RAG system testing and enable full vector search capabilities, we need PostgreSQL with the pgvector extension.

## Requirements

### Essential Components:
1. **PostgreSQL 12+** (preferably 15+ for best pgvector performance)
2. **pgvector extension** for vector similarity search
3. **Database connection** accessible from Python (asyncpg)

### Environment Variable Needed:
```bash
DATABASE_URL=postgresql://username:password@host:port/database_name
```

## Setup Options (Choose One)

### Option 1: Local PostgreSQL (Recommended for Development)

**1. Install PostgreSQL and pgvector:**

**macOS (using Homebrew):**
```bash
# Install PostgreSQL
brew install postgresql

# Start PostgreSQL service
brew services start postgresql

# Install pgvector extension
brew install pgvector

# Or build from source:
git clone --branch v0.5.1 https://github.com/pgvector/pgvector.git
cd pgvector
make
make install
```

**2. Create Database:**
```bash
# Connect to PostgreSQL
psql postgres

# Create database and user
CREATE DATABASE ragline;
CREATE USER ragline_user WITH PASSWORD 'your_secure_password';
GRANT ALL PRIVILEGES ON DATABASE ragline TO ragline_user;
\c ragline
CREATE EXTENSION vector;
\q
```

**3. Set Environment Variable:**
```bash
export DATABASE_URL=postgresql://ragline_user:your_secure_password@localhost:5432/ragline
```

### Option 2: Docker PostgreSQL (Quick Setup)

**1. Create docker-compose.yml:**
```yaml
version: '3.8'
services:
  postgres:
    image: ankane/pgvector
    environment:
      POSTGRES_DB: ragline
      POSTGRES_USER: ragline_user
      POSTGRES_PASSWORD: your_secure_password
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

**2. Start Database:**
```bash
docker-compose up -d
```

**3. Set Environment Variable:**
```bash
export DATABASE_URL=postgresql://ragline_user:your_secure_password@localhost:5432/ragline
```

### Option 3: Cloud Database (Production-Ready)

**Popular Options:**
- **Supabase** (has pgvector support): Easy setup, generous free tier
- **Neon** (PostgreSQL as a service): Built-in pgvector support
- **AWS RDS** with pgvector: Requires custom parameter group
- **Google Cloud SQL**: Supports pgvector extension

**Supabase Setup (Recommended Cloud Option):**
1. Go to [supabase.com](https://supabase.com)
2. Create a new project
3. Copy the connection string from Settings > Database
4. pgvector is already installed

## Testing the Setup

Once you have the database running, test the connection:

```bash
# Test basic connection
psql $DATABASE_URL -c "SELECT version();"

# Test pgvector extension
psql $DATABASE_URL -c "CREATE EXTENSION IF NOT EXISTS vector; SELECT * FROM pg_extension WHERE extname = 'vector';"
```

## What Happens Next

Once you provide the `DATABASE_URL`, I can:

1. **Test Vector Store Connection**
   - Initialize pgvector tables
   - Create vector indexes
   - Test embedding storage/retrieval

2. **Ingest Sample Data**
   - Load all 6 menu items with embeddings
   - Load 3 policy documents
   - Load 4 FAQ items
   - Total: ~13 documents with vector embeddings

3. **Test Full RAG Pipeline**
   - Real vector similarity search
   - Business rule re-ranking
   - Context formatting for LLM
   - End-to-end query → context workflow

4. **Performance Benchmarking**
   - Vector search latency (target: < 30ms)
   - Embedding generation time
   - Full RAG pipeline performance
   - Memory usage with real data

## Required Dependencies

I'll also install the PostgreSQL Python driver:

```bash
pip install asyncpg psycopg2-binary
```

## Recommended Approach

**For immediate testing:** Option 1 (Local PostgreSQL) or Option 2 (Docker)
**For production:** Option 3 (Cloud database like Supabase)

## What I Need From You

Just provide one of these:

1. **Local/Docker Setup:** 
   ```bash
   export DATABASE_URL=postgresql://username:password@localhost:5432/ragline
   ```

2. **Cloud Setup:** Your cloud database connection string

3. **Or let me know which option you prefer** and I can guide you through the specific setup steps.

Once you have the database ready, testing will take just a few minutes and we'll have a fully functional RAG system with real vector search capabilities!