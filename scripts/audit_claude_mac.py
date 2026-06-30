#!/usr/bin/env python3
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable


SECRET_WORDS = ("token", "key", "secret", "password", "authorization", "auth")
MODEL_WORDS = ("deepseek", "model", "provider", "api", "openai", "anthropic")
LOG_KEYWORDS = ("claude-image-bridge", "mcp", "error", "failed", "initialize", "tools/list")


def candidate_config_paths() -> list[Path]:
    paths = [
        Path.home() / "Library/Application Support/Claude-3p/claude_desktop_config.json",
        Path.home() / "Library/Application Support/Claude/claude_desktop_config.json",
    ]
    override = os.environ.get("CLAUDE_IMAGE_BRIDGE_CONFIG") or os.environ.get("CLAUDE_DESKTOP_CONFIG_PATH")
    if override:
        override_path = Path(override).expanduser()
        if override_path not in paths:
            paths.insert(0, override_path)
    return paths


def mask_value(key: str, value: Any) -> Any:
    if any(word in key.lower() for word in SECRET_WORDS):
        return "<masked>"
    if isinstance(value, dict):
        return {item_key: mask_value(item_key, item_value) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [mask_value(key, item) for item in value]
    return value


def mask_text(text: str) -> str:
    masked = text
    for word in SECRET_WORDS:
        masked = re.sub(
            rf"({word}[^:=\s]*\s*[:=]\s*)([^\s,}}]+)",
            rf"\1<masked>",
            masked,
            flags=re.IGNORECASE,
        )
    return masked


def format_mtime(path: Path) -> str:
    return _dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def print_running_processes() -> None:
    print("== running Claude-related processes ==")
    try:
        result = subprocess.run(["ps", "-ef"], capture_output=True, text=True, check=False)
    except Exception as exc:
        print(f"unable to inspect processes: {exc}")
        return
    needle = re.compile(r"Claude|Claude-3p|claude-image-bridge|bridge\.py", re.IGNORECASE)
    matches = [line for line in result.stdout.splitlines() if needle.search(line) and "audit_claude_mac.py" not in line]
    if not matches:
        print("none observed")
        return
    for line in matches[:20]:
        print(mask_text(line))
    if len(matches) > 20:
        print(f"... {len(matches) - 20} more lines omitted")


def possible_model_keys(keys: Iterable[str]) -> list[str]:
    return [key for key in keys if any(word in key.lower() for word in MODEL_WORDS)]


def print_config_summary(path: Path) -> None:
    print(f"== config: {path} ==")
    if not path.exists():
        print("missing")
        return
    print(f"mtime: {format_mtime(path)}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"invalid json: {exc}")
        return
    if not isinstance(data, dict):
        print(f"unexpected json root type: {type(data).__name__}")
        return

    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    print("mcp server names:", sorted(servers))
    if servers:
        print("mcp server configs (masked):", json.dumps(mask_value("mcpServers", servers), ensure_ascii=False))
    if "claude-image-bridge" in servers:
        print("existing claude-image-bridge:", json.dumps(mask_value("claude-image-bridge", servers["claude-image-bridge"]), ensure_ascii=False))

    top_keys = sorted(data.keys())
    print("top-level keys:", top_keys)
    print("possible model/provider keys:", possible_model_keys(top_keys))


def log_paths() -> list[Path]:
    return [
        Path.home() / "Library/Logs/Claude/mcp.log",
        Path.home() / "Library/Logs/Claude/mcp-server-claude-image-bridge.log",
        Path.home() / "Library/Logs/Claude-3p/mcp.log",
        Path.home() / "Library/Logs/Claude-3p/mcp-server-claude-image-bridge.log",
    ]


def print_log_summary(path: Path) -> None:
    print(f"== log: {path} ==")
    if not path.exists():
        print("missing")
        return
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        print(f"unable to read log: {exc}")
        return
    interesting = [
        mask_text(line)
        for line in lines[-200:]
        if any(keyword in line.lower() for keyword in LOG_KEYWORDS)
    ]
    if not interesting:
        print("no recent relevant lines")
        return
    for line in interesting[-20:]:
        print(line)


def main() -> int:
    print_running_processes()
    print()

    print("== installed app candidates ==")
    app_path = Path("/Applications/Claude.app")
    print(f"{app_path}: {'present' if app_path.exists() else 'missing'}")
    print()

    for path in candidate_config_paths():
        print_config_summary(path)
        print()

    for path in log_paths():
        print_log_summary(path)
        print()

    print("Audit complete. Review the chosen config path before running install.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
