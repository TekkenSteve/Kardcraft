# ============================================================================
# Kardcraft Makefile
# ============================================================================

.PHONY: help build build-all test test-all up down logs clean protobuf protobuf-lint protobuf-check

# 默认目标
help:
	@echo "Kardcraft 构建和部署工具"
	@echo ""
	@echo "可用命令:"
	@echo "  make build-all     构建所有服务"
	@echo "  make build-api     构建API网关"
	@echo "  make build-task    构建任务编排器"
	@echo "  make build-agent   构建Agent工作流"
	@echo "  make build-rust    构建Rust服务"
	@echo "  make build-storage 构建文件存储"
	@echo ""
	@echo "  make test-all      运行所有测试"
	@echo "  make test-api      测试API网关"
	@echo "  make test-task     测试任务编排器"
	@echo "  make test-agent    测试Agent工作流"
	@echo ""
	@echo "  make up            启动所有服务"
	@echo "  make up-core       仅启动核心服务"
	@echo "  make down          停止所有服务"
	@echo "  make logs          查看日志"
	@echo ""
	@echo "  make protobuf      生成protobuf代码"
	@echo "  make protobuf-lint 校验protobuf schema"
	@echo "  make protobuf-check 校验protobuf生成产物是否最新"
	@echo "  make clean         清理构建文件"

# ============================================================================
# 构建命令
# ============================================================================

build-all: build-api build-task build-agent build-rust build-storage

build-api:
	@echo "构建API网关..."
	cd backend/api-gateway && go build -o bin/api-gateway ./cmd/server

build-task:
	@echo "构建任务编排器..."
	cd backend/task-orchestrator && go build -o bin/task-orchestrator ./cmd/orchestrator

build-agent:
	@echo "构建Agent工作流..."
	cd backend/agent-workflow && pip install -e .

build-storage:
	@echo "构建文件存储..."
	cd backend/file-storage && go build -o bin/file-storage ./cmd/storage

# ============================================================================
# 测试命令
# ============================================================================

test-all: test-api test-task test-agent

test-api:
	@echo "测试API网关..."
	cd backend/api-gateway && go test ./...

test-task:
	@echo "测试任务编排器..."
	cd backend/task-orchestrator && go test ./...

test-agent:
	@echo "测试Agent工作流..."
	cd backend/agent-workflow && pytest tests/

test-guard:
	@echo "运行运行时引用守卫..."
	./scripts/check_no_rust_services_refs.sh
	./scripts/check_no_legacy_workspace_refs.sh
	./scripts/check_no_direct_litellm_calls.sh
	./scripts/check_execution_arch_guardrails.sh
	./scripts/check_no_runtime_ddl.sh
	./scripts/check_schema_drift.sh
	./scripts/check_protobuf_codegen.sh

# ============================================================================
# Docker命令
# ============================================================================

up:
	@echo "启动所有服务..."
	docker-compose up -d

up-core:
	@echo "启动核心服务..."
	docker-compose up -d redis postgres minio milvus

down:
	@echo "停止所有服务..."
	docker-compose down

logs:
	@echo "查看日志..."
	docker-compose logs -f

# ============================================================================
# 开发工具
# ============================================================================

protobuf:
	@echo "生成protobuf代码..."
	./backend/protobuf/generate.sh

protobuf-lint:
	@echo "校验protobuf schema..."
	cd backend/protobuf && buf lint

protobuf-check:
	@echo "检查protobuf生成产物是否最新..."
	./backend/protobuf/generate.sh
	git diff --exit-code -- backend/task-orchestrator/internal/proto backend/file-storage/pkg/grpc/pb backend/agent-workflow/src/kardcraft

clean:
	@echo "清理构建文件..."
	rm -rf backend/api-gateway/bin
	rm -rf backend/task-orchestrator/bin
	rm -rf backend/file-storage/bin
	rm -rf backend/agent-workflow/__pycache__
	rm -rf backend/agent-workflow/*.egg-info
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} +

# ============================================================================
# 部署命令
# ============================================================================

deploy-dev:
	@echo "部署到开发环境..."
	cd scripts/deploy && ./deploy-dev.sh

deploy-staging:
	@echo "部署到预发布环境..."
	cd scripts/deploy && ./deploy-staging.sh

deploy-prod:
	@echo "部署到生产环境..."
	cd scripts/deploy && ./deploy-prod.sh

# ============================================================================
# 数据库命令
# ============================================================================

db-migrate:
	@echo "运行数据库迁移..."
	cd backend/database/scripts && ./migrate.sh

db-seed:
	@echo "填充种子数据..."
	@echo "暂未配置统一 seeds 目录"

db-backup:
	@echo "备份数据库..."
	@echo "暂未配置统一 backup 脚本"

# ============================================================================
# 监控命令
# ============================================================================

monitor-up:
	@echo "启动监控服务..."
	docker-compose up -d prometheus grafana

monitor-down:
	@echo "停止监控服务..."
	docker-compose stop prometheus grafana

# ============================================================================
# 开发工具
# ============================================================================

dev-tools-up:
	@echo "启动开发工具..."
	docker-compose up -d pgadmin redis-commander minio-console

dev-tools-down:
	@echo "停止开发工具..."
	docker-compose stop pgadmin redis-commander minio-console
