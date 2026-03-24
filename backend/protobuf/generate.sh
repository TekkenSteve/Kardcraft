#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROTO_DIR="${PROJECT_ROOT}/backend/protobuf"
TARGET="${1:-all}"

cd "${PROJECT_ROOT}"

BUF_BIN="${BUF_BIN:-}"
if [[ -z "${BUF_BIN}" ]]; then
  if command -v buf >/dev/null 2>&1; then
    BUF_BIN="$(command -v buf)"
  fi
fi

if [[ -z "${BUF_BIN}" ]]; then
  echo "Error: 'buf' is not installed or not in PATH."
  echo "Hint: install buf and ensure it is in PATH, or run with BUF_BIN=/path/to/buf."
  echo "Install guide: https://buf.build/docs/installation"
  exit 1
fi

generate_core_protos() {
  echo "Generating protobuf stubs for core services (kardcraft + sandbox broker)..."
  mkdir -p "${PROJECT_ROOT}/backend/task-orchestrator/internal/proto"
  mkdir -p "${PROJECT_ROOT}/backend/agent-workflow/src/kardcraft"

  pushd "${PROTO_DIR}" >/dev/null
  "${BUF_BIN}" generate . \
    --template buf.gen.core.python.yaml \
    --path kardcraft.proto \
    --path sandbox_broker.proto

  "${BUF_BIN}" generate . \
    --template buf.gen.core.go.yaml \
    --path kardcraft.proto
  popd >/dev/null
}

generate_file_storage_protos() {
  echo "Generating protobuf stubs for file-storage..."
  mkdir -p "${PROJECT_ROOT}/backend/file-storage/pkg/grpc/pb"
  mkdir -p "${PROJECT_ROOT}/backend/agent-workflow/src/kardcraft"
  pushd "${PROTO_DIR}" >/dev/null
  "${BUF_BIN}" generate . \
    --template buf.gen.file_storage.yaml \
    --path file_storage.proto \
    --include-imports
  popd >/dev/null
}

fix_python_grpc_import() {
  local file="$1"
  if [[ ! -f "${file}" ]]; then
    return
  fi

  python3 - "${file}" <<'PY'
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
fixed = re.sub(
    r"^import ([A-Za-z0-9_]+_pb2) as (.+)$",
    r"from . import \1 as \2",
    text,
    flags=re.MULTILINE,
)
if fixed != text:
    path.write_text(fixed, encoding="utf-8")
PY
}

fix_python_imports() {
  echo "Fixing Python gRPC relative imports..."
  fix_python_grpc_import "${PROJECT_ROOT}/backend/agent-workflow/src/kardcraft/kardcraft_pb2_grpc.py"
  fix_python_grpc_import "${PROJECT_ROOT}/backend/agent-workflow/src/kardcraft/sandbox_broker_pb2_grpc.py"
  fix_python_grpc_import "${PROJECT_ROOT}/backend/agent-workflow/src/kardcraft/file_storage_pb2_grpc.py"

  # file_storage_pb2 imports "buf.validate.validate_pb2" as a top-level module.
  # Keep a mirrored top-level package under src/buf so runtime import works.
  local buf_pkg_src="${PROJECT_ROOT}/backend/agent-workflow/src/kardcraft/buf"
  local buf_pkg_dst="${PROJECT_ROOT}/backend/agent-workflow/src/buf"
  if [[ -d "${buf_pkg_src}" ]]; then
    rm -rf "${buf_pkg_dst}"
    cp -R "${buf_pkg_src}" "${buf_pkg_dst}"
  fi
}

case "${TARGET}" in
  all)
    generate_core_protos
    generate_file_storage_protos
    ;;
  core)
    generate_core_protos
    ;;
  file-storage)
    generate_file_storage_protos
    ;;
  *)
    echo "Unknown target: ${TARGET}"
    echo "Usage: ./backend/protobuf/generate.sh [all|core|file-storage]"
    exit 1
    ;;
esac

fix_python_imports
echo "Protobuf code generation completed."
