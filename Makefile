# Makefile for Trading Agent System
# Quick commands for common operations

.PHONY: help check test test-new syntax clean docker-up docker-down docker-logs

# Default target - show help
help:
	@echo "======================================"
	@echo "Trading Agent System - Make Commands"
	@echo "======================================"
	@echo ""
	@echo "Quality Control:"
	@echo "  make check        - Run all quality checks (syntax + tests)"
	@echo "  make test         - Run all tests"
	@echo "  make test-new     - Run only new tests (exchange, strategy, trailing stop)"
	@echo "  make syntax       - Check Python syntax"
	@echo ""
	@echo "Docker Operations:"
	@echo "  make docker-up    - Start all services"
	@echo "  make docker-down  - Stop all services"
	@echo "  make docker-logs  - Follow orchestrator logs"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean        - Remove Python cache and test artifacts"
	@echo ""

# Run all quality checks
check:
	@echo "Running quality checks..."
	@bash scripts/check.sh

# Run all tests
test:
	@echo "Running test suite..."
	python3 -m pytest -v --tb=short

# Run only new tests (without exchange marker)
test-new:
	@echo "Running new tests (exchange config, strategy, trailing stop)..."
	python3 -m pytest test_exchange_config.py test_strategy_selection.py test_stop_loss_trailing.py -v -m "not exchange"

# Check Python syntax
syntax:
	@echo "Checking Python syntax..."
	python3 -m compileall .

# Clean Python cache and test artifacts
clean:
	@echo "Cleaning Python cache and test artifacts..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	@echo "Cleanup complete!"

# Docker operations
docker-up:
	@echo "Starting Docker services..."
	docker-compose up -d
	@echo "Services started. Check logs with: make docker-logs"

docker-down:
	@echo "Stopping Docker services..."
	docker-compose down

docker-logs:
	@echo "Following orchestrator logs (Ctrl+C to exit)..."
	docker-compose logs -f orchestrator

# Install test dependencies
install-test-deps:
	@echo "Installing test dependencies..."
	pip3 install pytest pytest-asyncio
	@echo "Test dependencies installed!"
