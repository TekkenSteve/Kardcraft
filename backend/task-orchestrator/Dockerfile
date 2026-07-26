# syntax=docker/dockerfile:1

FROM golang:1.26-alpine AS builder
ARG TARGET=orchestrator
WORKDIR /src

# Download dependencies (cache layer)
COPY --from=goagent . /GoAgent
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download && go mod verify

# Copy the code and build (only changes in the code trigger this layer)
COPY . .
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -ldflags="-s -w" -o /out/task-orchestrator ./cmd/${TARGET}

# ========== Runtime ==========
FROM gcr.io/distroless/static-debian12:nonroot

WORKDIR /app
USER nonroot:nonroot

COPY --from=builder --chown=nonroot:nonroot /out/task-orchestrator /app/
COPY --chown=nonroot:nonroot config.yaml /app/

CMD ["/app/task-orchestrator"]
