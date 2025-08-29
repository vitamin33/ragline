# Agent A Unit Tests

Unit tests for Core API & Data layer components.

## Scope
- FastAPI routes and middleware
- SQLAlchemy models and database operations
- Security and authentication logic
- Cache layer functionality
- Data validation and serialization

## Structure
- `test_api_*.py` - API endpoint tests
- `test_auth_*.py` - Authentication and JWT tests  
- `test_db_*.py` - Database model and migration tests
- `test_cache_*.py` - Redis cache tests
- `test_security_*.py` - Security utility tests

## Running
```bash
pytest tests/unit/agent_a -m agent_a
```