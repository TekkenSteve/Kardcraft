# File Storage Service Makefile

.PHONY: help build run test clean proto docker-build docker-run

# Variables
SERVICE_NAME := file-storage
BINARY_NAME := storage
DOCKER_IMAGE := kardcraft/$(SERVICE_NAME)
PB_DIR := pkg/grpc/pb

# Default target
help: ## Show this help message
	@echo "Available targets:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# Build targets
build: proto ## Build the service binary
	@echo "Building $(SERVICE_NAME)..."
	go build -o bin/$(BINARY_NAME) ./cmd/storage

run: build ## Run the service locally
	@echo "Running $(SERVICE_NAME)..."
	./bin/$(BINARY_NAME)

# Protocol Buffers
proto: ## Generate protobuf code
	@echo "Generating protobuf code..."
	cd ../.. && ./backend/protobuf/generate.sh file-storage

# Testing
test: ## Run tests
	@echo "Running tests..."
	go test -v ./...

test-coverage: ## Run tests with coverage
	@echo "Running tests with coverage..."
	go test -v -coverprofile=coverage.out ./...
	go tool cover -html=coverage.out -o coverage.html

# Development
dev: ## Run in development mode with hot reload
	@echo "Running in development mode..."
	air -c .air.toml

# Dependencies
deps: ## Download dependencies
	@echo "Downloading dependencies..."
	go mod download
	go mod tidy

# Docker
docker-build: ## Build Docker image
	@echo "Building Docker image..."
	docker build -t $(DOCKER_IMAGE):latest .

docker-run: docker-build ## Run Docker container
	@echo "Running Docker container..."
	docker run --rm -p 50053:50053 \
		-e MINIO_ENDPOINT=host.docker.internal:9000 \
		-e MINIO_ACCESS_KEY=minioadmin \
		-e MINIO_SECRET_KEY=minioadmin \
		$(DOCKER_IMAGE):latest

# Cleanup
clean: ## Clean build artifacts
	@echo "Cleaning up..."
	rm -rf bin/
	rm -rf $(PB_DIR)/*.pb.go
	rm -f coverage.out coverage.html

# Linting
lint: ## Run linter
	@echo "Running linter..."
	golangci-lint run

# Format code
fmt: ## Format code
	@echo "Formatting code..."
	go fmt ./...

# Generate mocks
mocks: ## Generate mocks for testing
	@echo "Generating mocks..."
	mockgen -source=internal/storage/interface.go -destination=internal/storage/mocks/storage_mock.go

# Database migrations (if needed)
migrate-up: ## Run database migrations up
	@echo "Running migrations up..."
	# Add migration commands here if needed

migrate-down: ## Run database migrations down
	@echo "Running migrations down..."
	# Add migration commands here if needed

# Install tools
install-tools: ## Install development tools
	@echo "Installing development tools..."
	go install github.com/bufbuild/buf/cmd/buf@latest
	go install github.com/cosmtrek/air@latest
	go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest
	go install github.com/golang/mock/mockgen@latest

# Health check
health: ## Check service health
	@echo "Checking service health..."
	grpcurl -plaintext localhost:50053 file_storage.FileStorageService/GetHealth

# Examples
example-upload: ## Example file upload
	@echo "Example file upload..."
	# Add example upload command here

example-download: ## Example file download
	@echo "Example file download..."
	# Add example download command here
