# Cross-Agent Integration Tests

Integration tests that span multiple agents and test end-to-end workflows.

## Scope
- Complete order processing flows (A → B → C)
- Event propagation across services
- Contract compliance verification
- System health and observability
- Performance and load testing

## Structure  
- `test_order_flow_*.py` - End-to-end order processing
- `test_event_propagation_*.py` - Cross-service event tests
- `test_contract_compliance_*.py` - Schema validation tests
- `test_system_health_*.py` - Health check tests
- `test_performance_*.py` - Load and performance tests

## Running
```bash
pytest tests/integration/cross_agent -m integration
```

## Requirements
- All services must be running (API, Worker, LLM)
- Database and Redis must be available
- Test data fixtures loaded