.PHONY: help test lint type sec validate-contracts setup-all test-all

help:
	@echo "RAGline Development Commands"
	@echo "  make setup-all      - Setup all worktree environments"
	@echo "  make test-all       - Run all agent tests"
	@echo "  make lint           - Run linting"
	@echo "  make type           - Run type checking"
	@echo "  make sec            - Run security checks"
	@echo "  make validate       - Validate contracts"

setup-all:
	@echo "Setting up Python environments for all agents..."
	@for agent in a b c; do \
		echo "Setting up ragline-$$agent..."; \
		cd ../ragline-$$agent && \
		python -m venv .venv && \
		. .venv/bin/activate && \
		pip install -r requirements.txt; \
	done

test:
	pytest tests/ -v --cov=services --cov=packages --cov-report=term-missing

test-all:
	@echo "Running tests for all agents..."
	@cd ../ragline-a && make test
	@cd ../ragline-b && make test
	@cd ../ragline-c && make test

lint:
	ruff check services packages
	black --check services packages

type:
	mypy services packages --ignore-missing-imports

sec:
	bandit -r services packages
	safety check

validate-contracts:
	@echo "Validating OpenAPI..."
	@python -c "import yaml, json; yaml.safe_load(open('contracts/openapi.yaml'))"
	@echo "Validating event schemas..."
	@for file in contracts/events/*.json; do \
		python -c "import json; json.load(open('$$file'))" || exit 1; \
	done
	@echo "✅ All contracts valid"

merge-check:
	@echo "Checking for merge conflicts..."
	@for agent in a b c; do \
		echo "Checking ragline-$$agent..."; \
		cd ../ragline-$$agent && \
		git fetch origin && \
		git diff origin/main...HEAD --name-only; \
	done

daily-report:
	@echo "Generating daily progress report..."
	@python scripts/generate_daily_report.py > docs/DAILY_STATUS.md
