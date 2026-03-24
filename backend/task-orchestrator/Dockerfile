# syntax=docker/dockerfile:1

FROM golang:1.26-alpine AS builder
WORKDIR /src

# 下载依赖（缓存层）
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

# 复制代码并构建（代码变动只触发这层）
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -ldflags="-s -w" -o /out/task-orchestrator ./cmd/orchestrator && \
    go build -ldflags="-s -w" -o /out/task-worker ./cmd/worker

# ========== 运行时 ==========
FROM gcr.io/distroless/static-debian12:nonroot

WORKDIR /app
USER nonroot:nonroot

COPY --from=builder --chown=nonroot:nonroot /out/task-orchestrator /app/
COPY --from=builder --chown=nonroot:nonroot /out/task-worker /app/
COPY --chown=nonroot:nonroot config.yaml /app/

# # syntax=docker/dockerfile:1

# FROM golang:1.26-alpine AS builder
# WORKDIR /src

# COPY go.mod ./
# RUN --mount=type=cache,target=/go/pkg/mod \
#     --mount=type=cache,target=/root/.cache/go-build \
#     go mod download

# COPY . .
# RUN --mount=type=cache,target=/go/pkg/mod \
#     --mount=type=cache,target=/root/.cache/go-build \
#     CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /out/task-orchestrator ./cmd/orchestrator
# RUN --mount=type=cache,target=/go/pkg/mod \
#     --mount=type=cache,target=/root/.cache/go-build \
#     CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o /out/task-worker ./cmd/worker

# FROM alpine:3.21
# RUN apk add --no-cache ca-certificates tzdata wget
# WORKDIR /app
# COPY --from=builder /out/task-orchestrator /app/task-orchestrator
# COPY --from=builder /out/task-worker /app/task-worker
# COPY config.yaml /app/config.yaml
