# Protobuf in Kardcraft

This project uses a single protobuf source of truth under `backend/protobuf/` and uses [Buf](https://buf.build/) for generation and linting.

## Source Files

All protobuf definitions live in this directory:

- `kardcraft.proto`
- `sandbox_broker.proto`
- `file_storage.proto`

## Generation

From repo root:

```bash
make protobuf
```

Or call targets directly:

```bash
./backend/protobuf/generate.sh all
./backend/protobuf/generate.sh core
./backend/protobuf/generate.sh file-storage
```

Generated outputs:

- Go (task orchestrator): `backend/task-orchestrator/internal/proto`
- Go (file storage): `backend/file-storage/pkg/grpc/pb`
- Python (agent workflow): `backend/agent-workflow/src/kardcraft`

## Lint and Drift Check

```bash
make protobuf-lint
make protobuf-check
```

`protobuf-check` regenerates and fails if generated files are out of date.

## Buf Installation

`buf` must be available in `PATH`.

If your local binary is not in `PATH`, run generation with:

```bash
BUF_BIN=/absolute/path/to/buf ./backend/protobuf/generate.sh all
```

## Validation Rules

`file_storage.proto` uses `protovalidate` rules via `buf/validate/validate.proto`.

Dependency and lock files:

- `backend/protobuf/buf.yaml`
- `backend/protobuf/buf.lock`
