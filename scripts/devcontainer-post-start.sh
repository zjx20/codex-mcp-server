#!/usr/bin/env bash
set -euo pipefail

PORT="${CODEX_MCP_HTTP_PORT:-${MCP_HTTP_PORT:-8765}}"
HOST="${CODEX_MCP_HTTP_HOST:-0.0.0.0}"
MCP_PATH="${CODEX_MCP_HTTP_PATH:-/mcp}"
WORKDIR="${CODEX_MCP_CWD:-${PWD}}"
LOG_DIR="${CODEX_MCP_LOG_DIR:-/tmp/codex-mcp-server}"
LOG_FILE="${LOG_DIR}/server-${PORT}.log"
PID_FILE="${LOG_DIR}/server-${PORT}.pid"
CMD=(codex-mcp-server --transport http --host "${HOST}" --port "${PORT}" --path "${MCP_PATH}")

mkdir -p "${LOG_DIR}"

if pgrep -f "codex_mcp_server.*--transport http .*--port ${PORT}" >/dev/null 2>&1; then
    exit 0
fi

echo "Starting codex-mcp-server on ${HOST}:${PORT}${MCP_PATH} from ${WORKDIR}" >> "${LOG_FILE}"
cd "${WORKDIR}"

if command -v setsid >/dev/null 2>&1; then
    setsid env CODEX_MCP_CWD="${WORKDIR}" "${CMD[@]}" >> "${LOG_FILE}" 2>&1 < /dev/null &
else
    nohup env CODEX_MCP_CWD="${WORKDIR}" "${CMD[@]}" >> "${LOG_FILE}" 2>&1 < /dev/null &
fi

PID=$!
echo "${PID}" > "${PID_FILE}"
disown "${PID}"
