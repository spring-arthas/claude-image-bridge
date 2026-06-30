# Task: Enable Screenshot/Image Handling For Claude Desktop + DeepSeek On macOS

This task file is intended for Codex running on another Mac.

The target machine already has Claude Desktop connected to a DeepSeek text-only model. The goal is to install and verify this repository's local MCP image bridge so Claude Desktop can process screenshots/images by converting them into OCR/structured text before passing the result to DeepSeek.

## User prompt to start this task

Copy this prompt into Codex on the target Mac:

```text
请读取 GitHub 远程仓库 https://github.com/spring-arthas/claude-image-bridge。
仓库根目录有一个任务文件 TASK_MAC_CLAUDE_DESKTOP_DEEPSEEK_IMAGE_BRIDGE.md。
请严格按照这个任务文件执行：先 clone 仓库并审计本机已有 Claude Desktop 环境，不要直接安装；检查当前运行的 Claude/Claude-3p、已有 claude_desktop_config.json、已有 MCP servers、是否已存在 claude-image-bridge、DeepSeek 相关配置是否可能被影响，以及 Python、Swift、Pillow、sips、pdftoppm 状态。然后告诉我是否可以安装、会写入哪个配置文件、会保留哪些已有配置、备份路径是什么。我确认后再继续安装、重启 Claude Desktop 并验证 claude-image-bridge MCP 是否可用。
```

## Desired outcome

After completion:

- Claude Desktop can attach to MCP server `claude-image-bridge`.
- DeepSeek still remains text-only, but can reason over OCR/structured text extracted from pasted screenshots/images.
- The user can paste or copy a screenshot, then ask Claude Desktop to capture and analyze it through `claude-image-bridge`.
- Images are saved into a bridge-managed image session so earlier images in the same conversation can be listed and analyzed by `index` or `image_id`.

## Important constraints

- Do not assume the target Mac has the same paths as the source Mac.
- Do not assume the target Mac is a clean Claude Desktop installation. Treat it as an existing production-like local environment.
- Do not blindly copy a `claude_desktop_config.json` from another computer.
- Do not write Claude Desktop config until the existing-environment audit and doctor step have both been reviewed by the user.
- Do not remove, reorder, or rewrite unrelated existing MCP server entries.
- Do not alter the user's DeepSeek model/provider configuration. This project only adds or updates the `mcpServers.claude-image-bridge` entry.
- Do not create a duplicate `claude-image-bridge` entry if one already exists. Inspect it, report it, then update only after user confirmation.
- Do not print secrets from config files. Mask values whose keys contain `token`, `key`, `secret`, `password`, `authorization`, or `auth`.
- Do not request, print, or store GitHub tokens, API keys, Claude tokens, or DeepSeek tokens.
- Prefer the detected active Claude config path, usually one of:

```text
~/Library/Application Support/Claude-3p/claude_desktop_config.json
~/Library/Application Support/Claude/claude_desktop_config.json
```

- If both config files exist, do not choose only by path existence. Inspect the running app, existing MCP logs, config content, and modification time. If ambiguity remains, ask the user which Claude Desktop app they actually use before installing.

## Phase 1: Clone and inspect

Clone the repository:

```bash
git clone https://github.com/spring-arthas/claude-image-bridge.git
cd claude-image-bridge
```

Inspect the project:

```bash
ls
sed -n '1,220p' README.md
sed -n '1,220p' docs/MAC_MIGRATION_WITH_CODEX.md
```

Confirm these files exist:

```text
bridge.py
clipboard_capture.swift
vision_ocr.swift
mcp_smoke_test.py
requirements.txt
scripts/doctor_mac.sh
scripts/install_mac.sh
docs/IMPLEMENTATION_SUMMARY.md
docs/MAC_MIGRATION_WITH_CODEX.md
```

## Phase 2: Audit the existing Claude Desktop environment

This phase is mandatory on machines that already have Claude Desktop installed.

Do not install anything yet.

Check installed/running Claude apps:

```bash
ps -ef | rg -i 'Claude|Claude-3p|claude-image-bridge|bridge.py' || true
ls -ld /Applications/Claude.app 2>/dev/null || true
```

Check candidate config files:

```text
~/Library/Application Support/Claude-3p/claude_desktop_config.json
~/Library/Application Support/Claude/claude_desktop_config.json
```

For each config file that exists:

- Verify it is valid JSON.
- Report the config path and last modified time.
- Report the existing `mcpServers` server names.
- If `claude-image-bridge` already exists, report its `command` and `args`, but do not update it yet.
- Report whether the config appears to contain DeepSeek/provider/model-related entries, but do not print secrets or full provider credentials.

Use a masked summary. For example:

```bash
python3 - <<'PY'
import json, os
from pathlib import Path

paths = [
    Path.home() / "Library/Application Support/Claude-3p/claude_desktop_config.json",
    Path.home() / "Library/Application Support/Claude/claude_desktop_config.json",
]
secret_words = ("token", "key", "secret", "password", "authorization", "auth")

def mask_value(key, value):
    if any(word in key.lower() for word in secret_words):
        return "<masked>"
    if isinstance(value, dict):
        return {k: mask_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_value(key, item) for item in value]
    return value

for path in paths:
    print(f"== {path} ==")
    if not path.exists():
        print("missing")
        continue
    print("mtime:", path.stat().st_mtime)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print("invalid json:", exc)
        continue
    servers = data.get("mcpServers") if isinstance(data.get("mcpServers"), dict) else {}
    print("mcp server names:", sorted(servers))
    if "claude-image-bridge" in servers:
        print("existing claude-image-bridge:", mask_value("claude-image-bridge", servers["claude-image-bridge"]))
    top_keys = sorted(data.keys())
    print("top-level keys:", top_keys)
    possible_model_keys = [key for key in top_keys if any(word in key.lower() for word in ("deepseek", "model", "provider", "api", "openai", "anthropic"))]
    print("possible model/provider keys:", possible_model_keys)
PY
```

Check existing MCP logs if they exist:

```text
~/Library/Logs/Claude/mcp.log
~/Library/Logs/Claude/mcp-server-claude-image-bridge.log
~/Library/Logs/Claude-3p/mcp.log
~/Library/Logs/Claude-3p/mcp-server-claude-image-bridge.log
```

Report only useful attach/error summaries. Do not paste secrets.

Before moving to installation, prepare a short decision report:

```text
Existing Claude environment audit:
- Running Claude process: <yes/no/details>
- Candidate config files: <paths>
- Chosen config path: <path or undecided>
- Existing MCP servers that will be preserved: <names>
- Existing claude-image-bridge entry: <missing/existing path>
- DeepSeek/provider config: <present/not observed; not modified>
- Possible risk: <none/ambiguous config/existing bridge/wrong app>
```

If the chosen config path is uncertain, stop and ask the user. Do not continue.

## Phase 3: Run read-only dependency check

Run the doctor script first:

```bash
bash scripts/doctor_mac.sh
```

Report these findings to the user:

- macOS version.
- Whether `python3` exists.
- Whether `swift` exists.
- Whether `sips` exists.
- Whether `pdftoppm` exists. This is optional and only needed for PDF support.
- Whether system `python3` can import Pillow. If not, this is acceptable because the install script creates `.venv`.
- Which Claude config files exist:

```text
~/Library/Application Support/Claude-3p/claude_desktop_config.json
~/Library/Application Support/Claude/claude_desktop_config.json
```

Stop here and ask the user for confirmation before installing.

Recommended confirmation question:

```text
我检测到本机 Claude 配置文件为：<detected paths>。
已有 MCP servers 为：<server names>，这些会被保留。
已有 claude-image-bridge 状态为：<missing/existing and path>。
DeepSeek/provider 相关配置：<present/not observed>，不会被修改。
我将使用项目内 .venv 安装 Pillow，并只新增或更新 mcpServers.claude-image-bridge 到 <chosen config path>。
安装前会备份该配置文件。
是否确认继续安装？
```

## Phase 4: Install after user confirms

If only one Claude config path exists, use the default install flow:

```bash
bash scripts/install_mac.sh
```

If the target config path must be explicit, set `CLAUDE_IMAGE_BRIDGE_CONFIG` first:

```bash
export CLAUDE_IMAGE_BRIDGE_CONFIG="$HOME/Library/Application Support/Claude-3p/claude_desktop_config.json"
bash scripts/install_mac.sh
```

The install script should:

- Create `.venv` if needed.
- Install `requirements.txt`.
- Run `bridge.py self-test`.
- Update the chosen Claude Desktop config with MCP server `claude-image-bridge`.
- Preserve/merge existing `mcpServers` entries instead of replacing the whole config.
- Preserve DeepSeek/model/provider entries exactly as they are.
- Create or verify a backup of the config before writing.
- If an old `claude-image-bridge` entry existed, replace only that server's `command`/`args` with the current repository path after user confirmation.

After install, inspect the config again and confirm:

- JSON is still valid.
- Existing unrelated MCP servers are still present.
- `mcpServers.claude-image-bridge.command` points to this repository's `.venv` Python or chosen Python.
- `mcpServers.claude-image-bridge.args` points to this repository's `bridge.py serve`.

## Phase 5: Restart Claude Desktop

Restart Claude Desktop after installation.

If operating manually:

```bash
osascript -e 'tell application "Claude" to quit'
open -a Claude
```

If the app name is not exactly `Claude`, use the target Mac's actual app name.

## Phase 6: Verify MCP attach

Ask Claude Desktop:

```text
请列出 claude-image-bridge 可用工具。
```

Expected tools include:

```text
analyze_image
extract_text_from_image
normalize_image
analyze_clipboard_image
analyze_recent_screenshot
start_image_session
capture_pasted_image
list_pasted_images
analyze_pasted_image
```

If Claude Desktop reports:

```text
Could not attach to MCP server claude-image-bridge
```

then inspect:

```text
~/Library/Logs/Claude/mcp-server-claude-image-bridge.log
~/Library/Logs/Claude-3p/mcp-server-claude-image-bridge.log
~/Library/Logs/Claude/mcp.log
~/Library/Logs/Claude-3p/mcp.log
```

Check for:

- Wrong Python path in config.
- Wrong `bridge.py` path in config.
- Missing Pillow in `.venv`.
- `swift` unavailable.
- Config written to `Claude` while the running app uses `Claude-3p`, or the reverse.

## Phase 7: Verify screenshot/image workflow

In Claude Desktop, run:

```text
请调用 claude-image-bridge 的 start_image_session，label 为“图片测试”。
```

Copy or screenshot an image, then run:

```text
请调用 claude-image-bridge 的 capture_pasted_image，把我刚才复制或粘贴的图片保存到当前图片会话。
```

List images:

```text
请调用 claude-image-bridge 的 list_pasted_images，列出当前图片会话里的图片。
```

Analyze the latest unconsumed image:

```text
请调用 claude-image-bridge 的 analyze_pasted_image，which 使用 latest_unconsumed。
```

Also test analyzing an earlier image:

```text
请调用 claude-image-bridge 的 analyze_pasted_image，分析 index 为 1 的图片。
```

Success means Claude Desktop returns OCR text, summary, or structured UI analysis from the screenshot/image.

## Phase 8: Optional smoke test

If the user allows clipboard access and local GUI automation, run:

```bash
.venv/bin/python mcp_smoke_test.py
```

This test covers:

- MCP initialize.
- `tools/list`.
- direct image OCR.
- clipboard image analysis.
- image session creation.
- pasted image capture/list/analyze.
- JSON Lines MCP framing.

This smoke test may need non-sandbox permissions because it writes to the macOS clipboard.

## Completion report

When finished, report:

- Repository path on the target Mac.
- Claude config path updated.
- Backup config path.
- Existing MCP servers preserved.
- Whether an old `claude-image-bridge` entry was absent, preserved, or replaced.
- Whether `claude-image-bridge` appears in Claude Desktop.
- Whether screenshot capture and `analyze_pasted_image` succeeded.
- Any remaining limitations.

Important final wording:

```text
DeepSeek 本身仍不是原生多模态模型；当前能力是通过本地 MCP bridge 将截图/图片转换为 OCR 和结构化文本，再交给 DeepSeek 分析。
```
