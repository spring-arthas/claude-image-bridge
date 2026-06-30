# Task: Enable Screenshot/Image Handling For Claude Desktop + DeepSeek On macOS

This task file is intended for Codex running on another Mac.

The target machine already has Claude Desktop connected to a DeepSeek text-only model. The goal is to install and verify this repository's local MCP image bridge so Claude Desktop can process screenshots/images by converting them into OCR/structured text before passing the result to DeepSeek.

## User prompt to start this task

Copy this prompt into Codex on the target Mac:

```text
请读取 GitHub 远程仓库 https://github.com/spring-arthas/claude-image-bridge。
仓库根目录有一个任务文件 TASK_MAC_CLAUDE_DESKTOP_DEEPSEEK_IMAGE_BRIDGE.md。
请严格按照这个任务文件执行：先 clone 仓库并检查本机环境，不要直接安装；检查 Claude Desktop/Claude-3p 配置、Python、Swift、Pillow、sips、pdftoppm 状态后，告诉我是否可以安装以及会写入哪个配置文件。我确认后再继续安装、重启 Claude Desktop 并验证 claude-image-bridge MCP 是否可用。
```

## Desired outcome

After completion:

- Claude Desktop can attach to MCP server `claude-image-bridge`.
- DeepSeek still remains text-only, but can reason over OCR/structured text extracted from pasted screenshots/images.
- The user can paste or copy a screenshot, then ask Claude Desktop to capture and analyze it through `claude-image-bridge`.
- Images are saved into a bridge-managed image session so earlier images in the same conversation can be listed and analyzed by `index` or `image_id`.

## Important constraints

- Do not assume the target Mac has the same paths as the source Mac.
- Do not blindly copy a `claude_desktop_config.json` from another computer.
- Do not write Claude Desktop config until the doctor step has been reviewed by the user.
- Do not request, print, or store GitHub tokens, API keys, Claude tokens, or DeepSeek tokens.
- Prefer the detected active Claude config path, usually one of:

```text
~/Library/Application Support/Claude-3p/claude_desktop_config.json
~/Library/Application Support/Claude/claude_desktop_config.json
```

- If both config files exist, ask the user which Claude Desktop app they actually use before installing.

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

## Phase 2: Run read-only environment check

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
我将使用项目内 .venv 安装 Pillow，并把 claude-image-bridge MCP 写入 <chosen config path>。
是否确认继续安装？
```

## Phase 3: Install after user confirms

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

## Phase 4: Restart Claude Desktop

Restart Claude Desktop after installation.

If operating manually:

```bash
osascript -e 'tell application "Claude" to quit'
open -a Claude
```

If the app name is not exactly `Claude`, use the target Mac's actual app name.

## Phase 5: Verify MCP attach

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

## Phase 6: Verify screenshot/image workflow

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

## Phase 7: Optional smoke test

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
- Whether `claude-image-bridge` appears in Claude Desktop.
- Whether screenshot capture and `analyze_pasted_image` succeeded.
- Any remaining limitations.

Important final wording:

```text
DeepSeek 本身仍不是原生多模态模型；当前能力是通过本地 MCP bridge 将截图/图片转换为 OCR 和结构化文本，再交给 DeepSeek 分析。
```

