#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${ROOT}/.venv"
PYTHON="${VENV}/bin/python"

echo "== claude-image-bridge macOS install =="
echo "project: ${ROOT}"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi
if ! command -v swift >/dev/null 2>&1; then
  echo "swift is required for macOS clipboard/OCR helpers" >&2
  exit 1
fi
if ! command -v sips >/dev/null 2>&1; then
  echo "sips is required for HEIC/HEIF conversion" >&2
  exit 1
fi

if [[ ! -d "${VENV}" ]]; then
  python3 -m venv "${VENV}"
fi
"${PYTHON}" -m pip install --upgrade pip
"${PYTHON}" -m pip install -r "${ROOT}/requirements.txt"

echo
echo "== self test =="
"${PYTHON}" "${ROOT}/bridge.py" self-test >/tmp/claude-image-bridge-self-test.json
echo "self-test ok: /tmp/claude-image-bridge-self-test.json"

echo
echo "== install Claude Desktop MCP config =="
"${PYTHON}" "${ROOT}/bridge.py" install

echo
echo "Install complete. Restart Claude Desktop, then ask it to list claude-image-bridge tools."

