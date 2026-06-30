#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${ROOT}/.venv"
PYTHON="${VENV}/bin/python"

echo "== claude-image-bridge macOS install =="
echo "project: ${ROOT}"
echo

if [[ -z "${CLAUDE_IMAGE_BRIDGE_CONFIG:-}" && -z "${CLAUDE_DESKTOP_CONFIG_PATH:-}" ]]; then
  found_configs=()
  for app in "Claude-3p" "Claude"; do
    config="${HOME}/Library/Application Support/${app}/claude_desktop_config.json"
    if [[ -f "${config}" ]]; then
      found_configs+=("${config}")
    fi
  done
  if (( ${#found_configs[@]} > 1 )); then
    echo "Multiple Claude Desktop config files found:" >&2
    for config in "${found_configs[@]}"; do
      echo "  - ${config}" >&2
    done
    echo >&2
    echo "Set CLAUDE_IMAGE_BRIDGE_CONFIG to the config file you want to update, then rerun install." >&2
    echo "Example:" >&2
    echo "  export CLAUDE_IMAGE_BRIDGE_CONFIG=\"${found_configs[0]}\"" >&2
    exit 2
  fi
fi

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

echo "== existing Claude environment audit =="
python3 "${ROOT}/scripts/audit_claude_mac.py"
echo

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
