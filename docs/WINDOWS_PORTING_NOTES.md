# Windows Porting Notes

Windows is not supported by the current macOS implementation.

The reusable parts are:

- MCP JSON-RPC handling.
- Tool schema.
- Image session storage.
- Hash deduplication.
- Image selection by `image_id`, `index`, `latest`, `previous`, and `latest_unconsumed`.
- Pillow-based normalization for common image formats.

The macOS-specific parts that must be replaced are:

- `clipboard_capture.swift`: AppKit/NSPasteboard clipboard access.
- `vision_ocr.swift`: Apple Vision OCR.
- `sips`: HEIC/HEIF conversion.
- macOS Claude Desktop config path detection.

Possible Windows replacements:

- Clipboard: PowerShell/.NET clipboard APIs, `pywin32`, or `PIL.ImageGrab`.
- OCR: Windows.Media.Ocr, Tesseract, PaddleOCR, EasyOCR, or a local/remote OCR service.
- Config path: `%APPDATA%\Claude\claude_desktop_config.json` or `%APPDATA%\Claude-3p\claude_desktop_config.json`.
- Runtime temp path: `%TEMP%\claude-image-bridge`.

Recommended porting approach:

1. Split platform-specific clipboard and OCR code behind Python functions.
2. Keep the MCP/session API unchanged.
3. Add `scripts/doctor_windows.ps1`.
4. Add `scripts/install_windows.ps1`.
5. Add Windows smoke tests that do not require manual GUI interaction.

