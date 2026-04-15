# syntax=docker/dockerfile:1

FROM golang:1.26-alpine AS builder
WORKDIR /src

# Download dependencies (cache layer)
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download && go mod verify

# Copy the code and build (only changes in the code trigger this layer)
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -ldflags="-s -w" -o /out/task-orchestrator ./cmd/orchestrator && \
    go build -ldflags="-s -w" -o /out/task-worker ./cmd/worker

# ========== Runtime ==========
FROM gcr.io/distroless/static-debian12:nonroot

WORKDIR /app
USER nonroot:nonroot

COPY --from=builder --chown=nonroot:nonroot /out/task-orchestrator /app/
COPY --from=builder --chown=nonroot:nonroot /out/task-worker /app/
COPY --chown=nonroot:nonroot config.yaml /app/