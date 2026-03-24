# syntax=docker/dockerfile:1

# ============================================================================
# Build stage
# ============================================================================
FROM golang:1.26-alpine AS builder

WORKDIR /app

# 依赖定义（缓存层）
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

# 源码（独立层）
COPY . .

# 构建（利用缓存）
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -ldflags="-s -w" -o /out/storage ./cmd/storage

# ============================================================================
# Runtime stage
# ============================================================================
FROM gcr.io/distroless/static-debian12:nonroot

WORKDIR /app

# 从 builder 复制二进制和配置
COPY --from=builder --chown=nonroot:nonroot /out/storage /app/
COPY --from=builder --chown=nonroot:nonroot /app/config.yaml /app/

# distroless 已内置 nonroot 用户，无需创建
USER nonroot

CMD ["/app/storage"]
# # ============================================================================
# # Kardcraft File Storage Dockerfile
# # ============================================================================

# # Build stage
# FROM golang:1.24-alpine AS builder

# # Install build dependencies
# RUN apk add --no-cache git ca-certificates tzdata

# # Set working directory
# WORKDIR /app

# # Copy go mod files
# COPY go.mod go.sum ./

# # Download dependencies
# RUN go mod download

# # Copy source code
# COPY . .

# # Build the application
# RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o storage ./cmd/storage

# # Final stage
# FROM alpine:latest

# # Install ca-certificates for HTTPS requests
# RUN apk --no-cache add ca-certificates tzdata

# # Create non-root user
# RUN addgroup -g 1001 -S appgroup && \
#     adduser -u 1001 -S appuser -G appgroup

# # Set working directory
# WORKDIR /app

# # Copy binary from builder stage
# COPY --from=builder /app/storage .
# COPY --from=builder /app/config.yaml .

# # Change ownership to non-root user
# RUN chown -R appuser:appgroup /app

# # Switch to non-root user
# USER appuser

# # Expose ports (gRPC and HTTP)
# EXPOSE 50053 8080

# # Run the application
# CMD ["./storage"]