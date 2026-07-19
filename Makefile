# Kardcraft development commands

.DEFAULT_GOAL := up

COMPOSE := docker compose
PROTO_SCRIPT := ./backend/protobuf/generate.sh
PROTO_DIR := backend/protobuf

.PHONY: \
	help check-docker check-buf \
	up up-core down logs ps \
	protobuf protobuf-lint protobuf-check \
	build-all build-api build-task build-agent build-storage \
	test-all test-api test-task test-agent test-guard \
	db-migrate db-bootstrap-templates db-bootstrap-templates-force \
	db-check-template-bootstrap db-cutover-template-governance \
	db-verify-template-governance-empty-db clean

help: ## Show available commands
	@echo "Kardcraft commands"
	@echo ""
	@echo "Start"
	@echo "  make                 Generate protobuf code and start all services"
	@echo "  make up              Generate protobuf code and start all services"
	@echo "  make up-core         Start Redis, PostgreSQL, MinIO, and Milvus"
	@echo "  make down            Stop all services"
	@echo "  make logs            Follow service logs"
	@echo "  make ps              Show service status"
	@echo ""
	@echo "Code generation"
	@echo "  make protobuf        Generate all protobuf code"
	@echo "  make protobuf-lint   Lint protobuf files"
	@echo "  make protobuf-check  Check generated protobuf code"
	@echo ""
	@echo "Build and test"
	@echo "  make build-all       Build all local services"
	@echo "  make test-all        Run all tests and checks"
	@echo "  make test-guard      Run database guard checks"
	@echo ""
	@echo "Database"
	@echo "  make db-migrate                         Run database migrations"
	@echo "  make db-bootstrap-templates             Add missing template data"
	@echo "  make db-bootstrap-templates-force       Replace template data"
	@echo "  make db-check-template-bootstrap         Check template data"
	@echo ""
	@echo "Other"
	@echo "  make clean                              Remove local build files"

# Checks

check-docker: ## Check Docker access
	@command -v docker >/dev/null 2>&1 || { \
		echo "Error: Docker is not installed or not in PATH."; \
		exit 1; \
	}
	@$(COMPOSE) version >/dev/null 2>&1 || { \
		echo "Error: Docker Compose is not available."; \
		exit 1; \
	}
	@docker info >/dev/null 2>&1 || { \
		echo "Error: Docker is not running or this user cannot access it."; \
		echo "Run 'newgrp docker' once after adding your user to the docker group."; \
		exit 1; \
	}

check-buf: ## Check Buf access
	@command -v buf >/dev/null 2>&1 || { \
		echo "Error: Buf is required to generate protobuf code."; \
		echo "Install it from https://buf.build/docs/installation"; \
		echo "Then run make again."; \
		exit 1; \
	}

# Start and stop

up: protobuf check-docker ## Generate code and start all services
	@echo "Starting all services..."
	@$(COMPOSE) up -d

up-core: check-docker ## Start core services
	@echo "Starting core services..."
	@$(COMPOSE) up -d redis postgres minio milvus

down: check-docker ## Stop all services
	@echo "Stopping all services..."
	@$(COMPOSE) down

logs: check-docker ## Follow service logs
	@$(COMPOSE) logs -f

ps: check-docker ## Show service status
	@$(COMPOSE) ps

# Protobuf

protobuf: check-buf ## Generate protobuf code
	@echo "Generating protobuf code..."
	@$(PROTO_SCRIPT)

protobuf-lint: check-buf ## Lint protobuf files
	@echo "Linting protobuf files..."
	@cd $(PROTO_DIR) && buf lint

protobuf-check: protobuf ## Check generated protobuf code
	@git diff --exit-code -- backend/task-orchestrator/internal/proto backend/file-storage/pkg/grpc/pb backend/agent-workflow/src/kardcraft

# Build

build-all: build-api build-task build-agent build-storage ## Build all local services

build-api: ## Build the API gateway
	@echo "Building API gateway..."
	@cd backend/api-gateway && go build -o bin/api-gateway ./cmd/server

build-task: ## Build the task orchestrator
	@echo "Building task orchestrator..."
	@cd backend/task-orchestrator && go build -o bin/task-orchestrator ./cmd/orchestrator

build-agent: ## Install the agent workflow package
	@echo "Installing agent workflow..."
	@cd backend/agent-workflow && pip install -e .

build-storage: protobuf ## Build file storage
	@echo "Building file storage..."
	@cd backend/file-storage && go build -o bin/file-storage ./cmd/storage

# Test

test-all: test-api test-task test-agent test-guard ## Run all tests and checks

test-api: ## Test the API gateway
	@cd backend/api-gateway && go test ./...

test-task: ## Test the task orchestrator
	@cd backend/task-orchestrator && go test ./...

test-agent: ## Test the agent workflow
	@cd backend/agent-workflow && pytest tests/

test-guard: ## Run database guard checks
	@./backend/database/scripts/check_no_template_seed.sh
	@./backend/database/scripts/check_no_template_overwrite_in_migrations.sh

# Database

db-migrate: ## Run database migrations
	@./backend/database/scripts/migrate.sh

db-bootstrap-templates: ## Add missing template data
	@./backend/database/scripts/bootstrap_templates.sh

db-bootstrap-templates-force: ## Replace template data
	@./backend/database/scripts/bootstrap_templates.sh --force

db-check-template-bootstrap: ## Check template data
	@./backend/database/scripts/check_template_bootstrap.sh

db-cutover-template-governance: ## Run the template migration flow
	@./backend/database/scripts/cutover_template_governance.sh

db-verify-template-governance-empty-db: ## Test template setup on an empty database
	@./backend/database/scripts/verify_template_governance_empty_db.sh

# Cleanup

clean: ## Remove local build files
	@echo "Removing local build files..."
	@rm -rf backend/api-gateway/bin
	@rm -rf backend/task-orchestrator/bin
	@rm -rf backend/file-storage/bin
	@rm -rf backend/agent-workflow/__pycache__
	@rm -rf backend/agent-workflow/*.egg-info
	@find . -name "*.pyc" -delete
	@find . -name "__pycache__" -type d -exec rm -rf {} +
