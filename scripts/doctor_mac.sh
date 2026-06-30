#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== claude-image-bridge macOS doctor =="
echo "project: ${ROOT}"
echo

echo "== system =="
sw_vers || true
echo

echo "== commands =="
for cmd in python3 swift sips; do
  if command -v "${cmd}" >/dev/null 2>&1; then
    echo "ok: ${cmd} -> $(command -v "${cmd}")"
  else
    echo "missing: ${cmd}"
  fi
done
if command -v pdftoppm >/dev/null 2>&1; then
  echo "ok: pdftoppm -> $(command -v pdftoppm)"
else
  echo "optional missing: pdftoppm (install poppler only if PDF support is needed)"
fi
echo

echo "== Claude Desktop configs =="
for app in "Claude-3p" "Claude"; do
  config="${HOME}/Library/Application Support/${app}/claude_desktop_config.json"
  if [[ -f "${config}" ]]; then
    echo "found: ${config}"
  else
    echo "not found: ${config}"
  fi
done
if [[ -n "${CLAUDE_IMAGE_BRIDGE_CONFIG:-}" ]]; then
  echo "env override: CLAUDE_IMAGE_BRIDGE_CONFIG=${CLAUDE_IMAGE_BRIDGE_CONFIG}"
fi
echo

echo "== Python import check =="
if command -v python3 >/dev/null 2>&1; then
  python3 - <<'PY'
import sys
print("python:", sys.executable)
try:
    import PIL
    print("ok: Pillow", PIL.__version__)
except Exception as exc:
    print("missing: Pillow", exc)
PY
else
  echo "Skipping Python import check: python3 is missing"
fi
echo

echo "== existing Claude environment audit =="
if command -v python3 >/dev/null 2>&1; then
  python3 "${ROOT}/scripts/audit_claude_mac.py"
else
  echo "Skipping Claude environment audit: python3 is missing"
fi
echo

echo "Doctor complete. Run scripts/install_mac.sh only after checking the config path above."
