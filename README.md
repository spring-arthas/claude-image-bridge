# Claude Image Bridge

`claude-image-bridge` is a local MCP server for Claude Desktop setups where the selected model is text-only, for example DeepSeek-V4-Pro behind Claude Desktop.

It does not make the model natively multimodal. Instead, it reads a local image, clipboard image, screenshot, or PDF, runs local OCR and lightweight UI/text structuring, then returns text that the model can reason about.

## License and contributions

This project is public and open source under the MIT License.

Anyone can fork, use, modify, redistribute, and submit pull requests. GitHub still requires repository write permissions for direct pushes to the main repository, so outside contributors should use forks and pull requests.

## Why this repository exists

This project was extracted from a working company Mac setup after fixing a Claude Desktop + DeepSeek image-handling gap. It is intended to be cloned on another machine and inspected by Codex before installation.

Do not blindly copy the company machine's absolute paths. On another Mac, assume Claude Desktop may already have existing model/provider and MCP configuration. Run the task file first so Codex audits the local Claude environment, preserves existing entries, and only then installs the bridge after confirmation.

## Current platform support

- macOS: supported.
- Windows: not implemented yet. The MCP/session logic can be reused, but clipboard capture and OCR need Windows-specific replacements.

macOS uses:

- `clipboard_capture.swift` for AppKit/NSPasteboard clipboard access.
- `vision_ocr.swift` for Apple Vision OCR.
- `bridge.py` for MCP stdio, image normalization, OCR orchestration, session storage, and Claude Desktop config install.

## Main MCP tools

- `analyze_image`
- `extract_text_from_image`
- `normalize_image`
- `analyze_clipboard_image`
- `analyze_recent_screenshot`
- `start_image_session`
- `capture_pasted_image`
- `list_pasted_images`
- `analyze_pasted_image`

The session tools are the important part for pasted screenshots in a multi-turn conversation. They store images under a bridge-managed session directory and allow later analysis by `image_id`, `index`, `latest`, `previous`, or `latest_unconsumed`.

## macOS quick start

If you are using Codex on another Mac, the easiest path is to ask Codex to follow the repository task file. The task is designed for existing Claude Desktop environments, not only clean installs:

```text
请读取 GitHub 远程仓库 https://github.com/spring-arthas/claude-image-bridge，并按照仓库根目录的 TASK_MAC_CLAUDE_DESKTOP_DEEPSEEK_IMAGE_BRIDGE.md 完成任务。
```

Clone the repository, then run the read-only environment check:

```bash
cd claude-image-bridge
bash scripts/doctor_mac.sh
```

Review the detected Claude Desktop config paths. The bridge supports both:

```text
~/Library/Application Support/Claude-3p/claude_desktop_config.json
~/Library/Application Support/Claude/claude_desktop_config.json
```

If the config path is unusual, set it explicitly:

```bash
export CLAUDE_IMAGE_BRIDGE_CONFIG="$HOME/Library/Application Support/Claude-3p/claude_desktop_config.json"
```

Then install:

```bash
bash scripts/install_mac.sh
```

Restart Claude Desktop after installation.

## Test in Claude Desktop

Use explicit tool names if Claude does not call the MCP tools automatically:

```text
请调用 claude-image-bridge 的 start_image_session，label 为“图片测试”。
```

Copy or screenshot an image, then:

```text
请调用 capture_pasted_image，把我刚才粘贴的图片保存到当前图片会话。
```

List images:

```text
请调用 list_pasted_images，列出当前图片会话里的图片。
```

Analyze one:

```text
请调用 analyze_pasted_image，分析 index 为 1 的图片。
```

## Local storage

Runtime files are stored under the system temp directory:

```text
<tmp>/claude-image-bridge/
<tmp>/claude-image-bridge/pasted-images/
<tmp>/claude-image-bridge/pasted-images/state.json
```

On macOS this is usually under `/private/tmp`.

## Docs

- `TASK_MAC_CLAUDE_DESKTOP_DEEPSEEK_IMAGE_BRIDGE.md`: step-by-step task file for Codex on another Mac.
- `docs/IMPLEMENTATION_SUMMARY.md`: what was built and why.
- `docs/MAC_MIGRATION_WITH_CODEX.md`: recommended task prompt and procedure for another Mac.
- `docs/WINDOWS_PORTING_NOTES.md`: what must change for Windows support.
