# Mac Migration With Codex

Use this document on another Mac. The goal is to avoid blindly applying the source Mac's paths or assumptions.

## Recommended Codex prompt

```text
请读取当前仓库 claude-image-bridge。我的 Claude Desktop 已接入 DeepSeek 模型，但模型不能直接处理聊天框图片。请先运行 scripts/doctor_mac.sh 检查本机环境、Claude/Claude-3p 配置路径、Python/Swift/Pillow 状态，不要直接写配置。检查后告诉我是否可以安装；我确认后再运行 scripts/install_mac.sh，并重启 Claude Desktop 后验证 claude-image-bridge MCP 工具是否可用。
```

## Manual steps

1. Clone the repository.
2. Run:

```bash
bash scripts/doctor_mac.sh
```

3. Check which config exists:

```text
~/Library/Application Support/Claude-3p/claude_desktop_config.json
~/Library/Application Support/Claude/claude_desktop_config.json
```

4. If needed, set:

```bash
export CLAUDE_IMAGE_BRIDGE_CONFIG="/absolute/path/to/claude_desktop_config.json"
```

5. Install:

```bash
bash scripts/install_mac.sh
```

6. Restart Claude Desktop.
7. In Claude Desktop, ask:

```text
请列出 claude-image-bridge 可用工具。
```

## Success criteria

- Claude Desktop starts without `Could not attach to MCP server claude-image-bridge`.
- Tools list includes image/session tools.
- `start_image_session` returns a `session_id`.
- `capture_pasted_image` saves the current clipboard image.
- `list_pasted_images` shows at least one image.
- `analyze_pasted_image` returns OCR/structured text.

## If attach fails

Check Claude logs and the generated config. Common causes:

- Wrong Python path.
- Wrong `bridge.py` path.
- Missing Pillow.
- Swift command unavailable.
- Config written to `Claude` while the active app uses `Claude-3p`, or the reverse.

