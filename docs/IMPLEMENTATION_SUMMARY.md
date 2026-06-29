# Implementation Summary

## Problem

Claude Desktop was connected to a DeepSeek-V4-Pro style text-only model. The model could not analyze images pasted into the chat box. Native attachment vision was not available through that model path.

## Solution

Add a local MCP server named `claude-image-bridge`.

The bridge converts image input into text and structured metadata:

1. Claude Desktop calls an MCP tool.
2. The bridge reads an image from a local path, data URL, clipboard, recent screenshot, or image session.
3. The bridge normalizes the image with Pillow.
4. macOS Vision OCR extracts Chinese/English text and bounding boxes.
5. Python classifies common UI text as fields, buttons, menus, links, bullets, and descriptions.
6. The bridge returns JSON text to Claude Desktop.
7. The text-only model reasons over that returned text.

## MCP attach fix

The original server only handled `Content-Length` MCP framing. Claude Desktop may use JSON Lines for stdio MCP messages. The bridge now supports both:

- `Content-Length: ...` headers.
- One JSON-RPC message per line.

This fixed the startup error:

```text
Could not attach to MCP server claude-image-bridge
```

## Image session model

The bridge cannot reliably read Claude Desktop's internal chat session id through MCP. Instead, it creates an explicit bridge image session.

Important tools:

- `start_image_session`: creates or resumes a bridge-managed session.
- `capture_pasted_image`: saves the current clipboard image/file into that session.
- `list_pasted_images`: lists captured images with `index`, `image_id`, path, hash, timestamp, and consumed state.
- `analyze_pasted_image`: analyzes by `image_id`, `index`, `latest`, `previous`, or `latest_unconsumed`.

This supports multi-image conversations and lets the user refer to earlier screenshots.

## Storage

Session state lives under:

```text
<tmp>/claude-image-bridge/pasted-images/state.json
```

Session images live under:

```text
<tmp>/claude-image-bridge/pasted-images/<bridge_session_id>/
```

Images are hash-deduplicated and capped per session.

## macOS dependencies

- Python 3.
- Pillow.
- Swift.
- AppKit/NSPasteboard for clipboard capture.
- Apple Vision for OCR.
- `sips` for HEIC/HEIF conversion.
- Optional `pdftoppm` from poppler for PDF page rendering.

## Verification performed on the source Mac

- Python syntax check.
- `bridge.py self-test`.
- MCP smoke test with both MCP framing styles.
- Claude Desktop restart and log verification.
- Confirmed attach sequence: initialize, initialized notification, tools/list.

