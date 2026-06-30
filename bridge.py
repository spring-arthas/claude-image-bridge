#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from PIL import Image, ImageSequence, ImageDraw


ROOT = Path(__file__).resolve().parent
SWIFT_HELPER = ROOT / "vision_ocr.swift"
CLIPBOARD_HELPER = ROOT / "clipboard_capture.swift"
SWIFT_CACHE = Path(tempfile.gettempdir()) / "claude-image-bridge-swift-cache"
WORK_DIR = Path(tempfile.gettempdir()) / "claude-image-bridge"
RUNTIME_HOME = WORK_DIR / "runtime-home"
RUNTIME_TMP = WORK_DIR / "runtime-tmp"
IMAGE_INBOX_DIR = WORK_DIR / "pasted-images"
IMAGE_STATE_PATH = IMAGE_INBOX_DIR / "state.json"
WORK_DIR.mkdir(parents=True, exist_ok=True)
SWIFT_CACHE.mkdir(parents=True, exist_ok=True)
RUNTIME_HOME.mkdir(parents=True, exist_ok=True)
RUNTIME_TMP.mkdir(parents=True, exist_ok=True)
IMAGE_INBOX_DIR.mkdir(parents=True, exist_ok=True)

MAX_OCR_SIDE = 2400
MAX_GIF_FRAMES = 20
PDF_DPI = 200
MAX_SESSION_IMAGES = 100
CLIPBOARD_WATCH_INTERVAL_SECONDS = 2.0
def _resolve_claude_config_path() -> Path:
    configured = os.environ.get("CLAUDE_IMAGE_BRIDGE_CONFIG") or os.environ.get("CLAUDE_DESKTOP_CONFIG_PATH")
    if configured:
        return Path(configured).expanduser()

    candidates = [
        Path.home() / "Library/Application Support/Claude-3p",
        Path.home() / "Library/Application Support/Claude",
    ]
    for app_support in candidates:
        config_path = app_support / "claude_desktop_config.json"
        if config_path.exists():
            return config_path
    for app_support in candidates:
        if app_support.exists():
            return app_support / "claude_desktop_config.json"
    return candidates[-1] / "claude_desktop_config.json"


CLAUDE_CONFIG_PATH = _resolve_claude_config_path()
CLAUDE_APP_SUPPORT = CLAUDE_CONFIG_PATH.parent
SCREENSHOT_DIRS = [
    Path.home() / "Desktop",
    Path.home() / "Downloads",
    Path.home() / "Pictures",
]
SCREENSHOT_PATTERNS = [
    "Screen Shot *.png",
    "Screen Shot *.jpg",
    "Screen Shot *.jpeg",
    "Screenshot *.png",
    "Screenshot *.jpg",
    "Screenshot *.jpeg",
]

BUTTON_WORDS_ZH = {
    "确定",
    "取消",
    "保存",
    "关闭",
    "复制",
    "编辑",
    "上传",
    "下载",
    "下一步",
    "上一步",
    "添加",
    "删除",
    "返回",
    "搜索",
    "重试",
    "继续",
    "忽略",
    "完成",
    "提交",
    "重命名",
    "新建",
    "确认",
    "展开",
    "收起",
    "刷新",
    "切换",
    "选择",
    "浏览",
    "查看",
    "更多",
}
BUTTON_WORDS_EN = {
    "ok",
    "cancel",
    "save",
    "close",
    "copy",
    "edit",
    "upload",
    "download",
    "next",
    "back",
    "continue",
    "submit",
    "delete",
    "create",
    "new",
    "more",
    "retry",
    "refresh",
    "select",
    "apply",
}
MENU_WORDS_ZH = {
    "文件",
    "编辑",
    "视图",
    "帮助",
    "设置",
    "工具",
    "窗口",
    "账户",
    "个人中心",
    "更多",
    "选项",
    "偏好设置",
    "退出",
    "通知",
    "历史",
    "关于",
}
MENU_WORDS_EN = {
    "file",
    "edit",
    "view",
    "help",
    "settings",
    "tools",
    "window",
    "account",
    "more",
    "options",
    "preferences",
    "exit",
    "notifications",
    "history",
    "about",
}

FORM_FIELD_KEYWORDS = {
    "client id",
    "client secret",
    "authorization url",
    "token url",
    "scopes",
    "传输方式",
    "mcp server url",
    "插件id",
    "插件密钥",
    "user key",
}


class BridgeError(RuntimeError):
    pass


_IMAGE_STATE_LOCK = threading.RLock()
_CLIPBOARD_WATCHER_STARTED = False


def _debug(msg: str) -> None:
    print(f"[image-bridge] {msg}", file=sys.stderr)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _ensure_file(path: Path) -> Path:
    if not path.exists():
        raise BridgeError(f"file not found: {path}")
    if not path.is_file():
        raise BridgeError(f"not a file: {path}")
    return path


def _absolute_preserving_alias(path: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _decode_data_url(data_url: str) -> Tuple[bytes, str]:
    if not data_url.startswith("data:"):
        raise BridgeError("data_url must start with data:")
    header, payload = data_url.split(",", 1)
    mime = "application/octet-stream"
    if ";" in header:
        mime = header[5 : header.index(";")]
    elif header[5:]:
        mime = header[5:]
    if ";base64" not in header:
        raise BridgeError("only base64 data URLs are supported")
    return base64.b64decode(payload), mime


def _swift_json_helper(script: Path, args: Sequence[str]) -> Dict[str, Any]:
    if not script.exists():
        raise BridgeError(f"swift helper missing: {script}")
    cmd = [
        "swift",
        "-module-cache-path",
        str(SWIFT_CACHE),
        str(script),
        *args,
    ]
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(RUNTIME_HOME),
            "TMPDIR": str(RUNTIME_TMP),
            "XDG_CACHE_HOME": str(WORK_DIR / "xdg-cache"),
            "XDG_CONFIG_HOME": str(WORK_DIR / "xdg-config"),
        }
    )
    Path(env["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)
    Path(env["XDG_CONFIG_HOME"]).mkdir(parents=True, exist_ok=True)
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise BridgeError(result.stderr.strip() or result.stdout.strip() or "swift helper failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BridgeError(f"swift helper returned invalid JSON: {result.stdout[:500]}") from exc


def _read_clipboard_sources() -> List[Path]:
    payload = _swift_json_helper(CLIPBOARD_HELPER, [])
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    sources: List[Path] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        path = item.get("path")
        if kind in {"file", "image", "pdf"} and isinstance(path, str):
            candidate = Path(path)
            if candidate.exists():
                sources.append(candidate)
        elif kind == "text" and isinstance(path, str):
            candidate = Path(path)
            if candidate.exists():
                sources.append(candidate)
    return sources


def _latest_screenshot_file() -> Optional[Path]:
    candidates: List[Path] = []
    for root in SCREENSHOT_DIRS:
        if not root.exists():
            continue
        for pattern in SCREENSHOT_PATTERNS:
            candidates.extend(root.glob(pattern))
    candidates = [path for path in candidates if path.is_file()]
    if not candidates:
        return None
    candidates.sort(key=lambda path: (path.stat().st_mtime, path.name))
    return candidates[-1]


def _open_image(path: Path) -> Image.Image:
    try:
        return Image.open(path)
    except Exception as first_error:
        suffix = path.suffix.lower()
        if suffix in {".heic", ".heif"}:
            converted = _convert_with_sips(path)
            return Image.open(converted)
        raise BridgeError(f"cannot open image: {path}") from first_error


def _convert_with_sips(path: Path) -> Path:
    out = WORK_DIR / f"{path.stem}-{_sha256_file(path)[:12]}.png"
    if out.exists():
        return out
    cmd = ["sips", "-s", "format", "png", str(path), "--out", str(out)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise BridgeError(f"sips conversion failed for {path}: {result.stderr.strip()}")
    if not out.exists():
        raise BridgeError(f"sips did not produce output for {path}")
    return out


def _normalize_frame(frame: Image.Image) -> Image.Image:
    frame = frame.copy()
    try:
        exif = frame.getexif()
        orientation = exif.get(274)
        if orientation == 3:
            frame = frame.rotate(180, expand=True)
        elif orientation == 6:
            frame = frame.rotate(270, expand=True)
        elif orientation == 8:
            frame = frame.rotate(90, expand=True)
    except Exception:
        pass

    if frame.mode in {"RGBA", "LA"}:
        background = Image.new("RGBA", frame.size, (255, 255, 255, 255))
        background.alpha_composite(frame.convert("RGBA"))
        frame = background.convert("RGB")
    elif frame.mode != "RGB":
        frame = frame.convert("RGB")
    return frame


def _downscale_for_ocr(frame: Image.Image) -> Image.Image:
    width, height = frame.size
    longest = max(width, height)
    if longest <= MAX_OCR_SIDE:
        return frame
    scale = MAX_OCR_SIDE / float(longest)
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    resampling = getattr(Image, "Resampling", Image)
    return frame.resize(new_size, resampling.LANCZOS)


def _save_frame_png(frame: Image.Image, prefix: str, index: int) -> Path:
    out = WORK_DIR / f"{prefix}-{index:04d}.png"
    frame.save(out, format="PNG", optimize=True)
    return out


def _render_pdf_pages(path: Path) -> List[Dict[str, Any]]:
    prefix = WORK_DIR / f"{path.stem}-{_sha256_file(path)[:12]}"
    for old in WORK_DIR.glob(f"{prefix.name}-*.png"):
        try:
            old.unlink()
        except OSError:
            pass

    cmd = [
        "pdftoppm",
        "-png",
        "-r",
        str(PDF_DPI),
        str(path),
        str(prefix),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise BridgeError(f"pdftoppm conversion failed for {path}: {result.stderr.strip()}")

    page_files = sorted(
        WORK_DIR.glob(f"{prefix.name}-*.png"),
        key=lambda page: int(re.search(r"-(\d+)\.png$", page.name).group(1)),
    )
    if not page_files:
        raise BridgeError(f"pdftoppm did not produce pages for {path}")

    frames: List[Dict[str, Any]] = []
    for index, page_path in enumerate(page_files):
        try:
            with Image.open(page_path) as page:
                size = list(page.size)
        except Exception:
            size = []
        frames.append(
            {
                "index": index,
                "source_path": str(path),
                "frame_path": str(page_path),
                "size": size,
                "format": "PDF",
                "page": index + 1,
            }
        )
    return frames


def _prepare_ocr_input(path: Path) -> Path:
    with Image.open(path) as source:
        frame = _downscale_for_ocr(_normalize_frame(source))
        prepared = WORK_DIR / f"{path.stem}-ocr-{_sha256_file(path)[:12]}.png"
        frame.save(prepared, format="PNG", optimize=True)
        return prepared


def _extract_frames(path: Path) -> List[Dict[str, Any]]:
    if path.suffix.lower() == ".pdf":
        return _render_pdf_pages(path)

    source = _open_image(path)
    frames: List[Dict[str, Any]] = []
    frame_count = getattr(source, "n_frames", 1) or 1
    is_animated = bool(getattr(source, "is_animated", False)) or frame_count > 1

    if is_animated:
        if frame_count > MAX_GIF_FRAMES:
            frame_count = MAX_GIF_FRAMES
        for index, raw_frame in enumerate(ImageSequence.Iterator(source)):
            if index >= MAX_GIF_FRAMES:
                break
            frame = _normalize_frame(raw_frame)
            frame = _downscale_for_ocr(frame)
            png = _save_frame_png(frame, path.stem, index)
            frames.append(
                {
                    "index": index,
                    "source_path": str(path),
                    "frame_path": str(png),
                    "size": list(frame.size),
                    "format": source.format,
                }
            )
        return frames

    frame = _downscale_for_ocr(_normalize_frame(source))
    png = _save_frame_png(frame, path.stem, 0)
    frames.append(
        {
            "index": 0,
            "source_path": str(path),
            "frame_path": str(png),
            "size": list(frame.size),
            "format": source.format,
        }
    )
    return frames


def _swift_ocr(image_path: Path) -> Dict[str, Any]:
    if not SWIFT_HELPER.exists():
        raise BridgeError(f"swift helper missing: {SWIFT_HELPER}")
    cmd = [
        "swift",
        "-module-cache-path",
        str(SWIFT_CACHE),
        str(SWIFT_HELPER),
        str(image_path),
    ]
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(RUNTIME_HOME),
            "TMPDIR": str(RUNTIME_TMP),
            "XDG_CACHE_HOME": str(WORK_DIR / "xdg-cache"),
            "XDG_CONFIG_HOME": str(WORK_DIR / "xdg-config"),
        }
    )
    Path(env["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)
    Path(env["XDG_CONFIG_HOME"]).mkdir(parents=True, exist_ok=True)
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        raise BridgeError(
            "vision OCR failed: " + (result.stderr.strip() or result.stdout.strip() or "unknown error")
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BridgeError(f"vision OCR returned invalid JSON: {result.stdout[:500]}") from exc


def _build_prompt(result: Dict[str, Any]) -> str:
    ui_layout = result.get("ui_analysis", {}).get("layout_hint", "")
    parts = [
        f"Summary: {result.get('summary', '')}",
        f"UI layout: {ui_layout}",
        "Instructions: treat ui_analysis as the primary structured output; if layout is form_or_dialog, read form_fields first, then buttons, menu_items, links, bullets, and descriptions; ignore noise unless explicitly needed.",
        f"Source: {result.get('source_path', '')}",
        f"Format: {result.get('format', '')}",
        f"Pages/Frames: {len(result.get('frames', []))}",
        "",
        "OCR output:",
    ]
    for frame in result.get("frames", []):
        parts.append(f"[frame {frame['index']}] {frame.get('text', '').strip()}")
    return "\n".join(parts).strip()


def _collect_ocr_lines(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    collected: List[Dict[str, Any]] = []
    for frame_index, frame in enumerate(result.get("frames", [])):
        size = frame.get("size") or []
        frame_width = size[0] if len(size) >= 1 else None
        frame_height = size[1] if len(size) >= 2 else None
        for line_index, line in enumerate(frame.get("lines", [])):
            bbox = line.get("boundingBox") or {}
            text = str(line.get("text") or "").strip()
            if not text:
                continue
            collected.append(
                {
                    "frame_index": frame_index,
                    "line_index": line_index,
                    "text": text,
                    "confidence": line.get("confidence"),
                    "bbox": bbox,
                    "frame_width": frame_width,
                    "frame_height": frame_height,
                }
            )

    collected.sort(
        key=lambda item: (
            item["frame_index"],
            -(item["bbox"].get("y") or 0.0),
            item["bbox"].get("x") or 0.0,
        )
    )
    return collected


def _is_url(text: str) -> bool:
    normalized = text.strip().lower().replace(" ", "")
    if normalized.startswith(("http://", "https://", "http:/", "https:/", "www.")):
        return "." in normalized
    return bool(re.match(r"^https?://\S+$", text.strip(), re.I))


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _classify_ui_line(item: Dict[str, Any]) -> Dict[str, Any]:
    text = _normalize_text(item["text"])
    lower = text.lower()
    bbox = item.get("bbox") or {}
    width = bbox.get("width") or 0.0
    x = bbox.get("x") or 0.0
    frame_width = item.get("frame_width") or 1.0
    width_ratio = width if width <= 1 else width / float(frame_width)
    x_ratio = x if x <= 1 else x / float(frame_width)

    compact = re.sub(r"[\s\u3000]+", "", text)
    if len(compact) <= 4 and not re.search(r"[A-Za-z0-9\u4e00-\u9fff]{2,}", compact):
        return {"kind": "noise", "text": text}
    if len(compact) <= 3 and (x_ratio > 0.9 or width_ratio < 0.03 or re.fullmatch(r"[\W_]+", compact or "")):
        return {"kind": "noise", "text": text}

    if _is_url(text):
        return {"kind": "link", "text": text}

    if text.startswith(("•", "-", "*", "·", "◦", "●")) or re.match(r"^\d+[).、]", text):
        return {"kind": "bullet", "text": text}

    if "：" in text or ":" in text:
        label, value = re.split(r"[:：]", text, maxsplit=1)
        label = label.strip()
        value = value.strip()
        label_key = label.lower()
        if len(label) <= 30 and (
            label_key in FORM_FIELD_KEYWORDS
            or any(keyword in label_key for keyword in FORM_FIELD_KEYWORDS)
            or any(keyword in label for keyword in ("传输方式", "MCP Server URL", "插件ID", "插件密钥", "User Key"))
        ):
            if text.endswith(("：", ":")) or not value:
                return {"kind": "form_label", "label": label, "value": "", "state": "empty"}
            return {
                "kind": "form_pair",
                "label": label,
                "value": value,
                "state": "filled" if value else "empty",
            }
        if len(label) > 30 and not value:
            return {"kind": "description", "text": text}
        if text.endswith(("：", ":")) and len(label) > 30:
            return {"kind": "description", "text": text}
        if value and len(label) <= 30:
            return {
                "kind": "form_pair",
                "label": label,
                "value": value,
                "state": "filled" if value else "empty",
            }
        return {
            "kind": "description",
            "text": text,
        }

    if (
        compact in BUTTON_WORDS_ZH
        or lower in BUTTON_WORDS_EN
        or (len(compact) <= 8 and compact in BUTTON_WORDS_ZH)
        or (2 <= len(text) <= 10 and width_ratio < 0.18 and (x_ratio > 0.75 or x_ratio < 0.12))
    ):
        return {"kind": "button", "text": text}

    if compact in MENU_WORDS_ZH or lower in MENU_WORDS_EN:
        return {"kind": "menu", "text": text}

    if len(text) <= 8 and width_ratio < 0.16 and (" " not in text or text.isupper()):
        return {"kind": "control", "text": text}

    if len(text) >= 20:
        return {"kind": "description", "text": text}

    return {"kind": "text", "text": text}


def _summarize_result(result: Dict[str, Any]) -> Dict[str, Any]:
    text = result.get("text", "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    joined = "\n".join(lines)
    ui_lines = _collect_ocr_lines(result)
    classified_lines = [_classify_ui_line(item) for item in ui_lines]
    chinese_chars = sum(1 for ch in joined if "\u4e00" <= ch <= "\u9fff")
    ascii_chars = sum(1 for ch in joined if ch.isascii() and ch.isalpha())

    field_patterns = [
        "Client ID",
        "Client Secret",
        "Authorization URL",
        "Token URL",
        "Scopes",
        "传输方式",
        "MCP Server URL",
        "插件ID",
        "插件密钥",
        "User Key",
    ]

    detected_fields: List[Dict[str, str]] = []
    for pattern in field_patterns:
        if pattern in joined:
            detected_fields.append(
                {
                    "label": pattern,
                    "status": "present",
                }
            )

    missing_labels = [
        line[:-1].strip()
        for line in lines
        if line.endswith(":")
        and len(line) < 120
        and any(key.lower() in line.lower() for key in ("client id", "client secret", "authorization url", "token url", "scopes"))
    ]

    if chinese_chars > 10:
        language_hint = "zh-Hans"
    elif ascii_chars > chinese_chars:
        language_hint = "en-US"
    else:
        language_hint = "mixed"

    visible_points = []
    for label in ("传输方式", "MCP Server URL", "Client ID", "Client Secret", "Authorization URL", "Token URL", "Scopes"):
        if label in joined:
            visible_points.append(label)

    form_fields: List[Dict[str, Any]] = []
    buttons: List[str] = []
    menus: List[str] = []
    links: List[str] = []
    bullets: List[str] = []
    descriptions: List[str] = []
    noise: List[str] = []
    text_items: List[str] = []

    for item, classified in zip(ui_lines, classified_lines):
        kind = classified["kind"]
        text_value = classified.get("text") or classified.get("label") or item["text"]
        if kind in {"form_pair", "form_label"}:
            form_fields.append(classified)
            text_items.append(text_value)
        elif kind == "button":
            buttons.append(text_value)
            text_items.append(text_value)
        elif kind == "menu":
            menus.append(text_value)
            text_items.append(text_value)
        elif kind == "link":
            links.append(text_value)
            text_items.append(text_value)
        elif kind == "bullet":
            bullets.append(text_value)
            text_items.append(text_value)
        elif kind == "description":
            descriptions.append(text_value)
            text_items.append(text_value)
        elif kind == "noise":
            noise.append(text_value)
        else:
            text_items.append(text_value)

    # Merge duplicate form labels while preserving order.
    unique_form_fields: List[Dict[str, Any]] = []
    seen_fields = set()
    for field in form_fields:
        key = (field.get("kind"), field.get("label"), field.get("value"))
        if key in seen_fields:
            continue
        seen_fields.add(key)
        unique_form_fields.append(field)

    buttons = list(dict.fromkeys(buttons))
    menus = list(dict.fromkeys(menus))
    links = list(dict.fromkeys(links))
    bullets = list(dict.fromkeys(bullets))
    descriptions = list(dict.fromkeys(descriptions))
    noise = list(dict.fromkeys(noise))
    text_items = list(dict.fromkeys(text_items))

    if unique_form_fields:
        layout_hint = "form_or_dialog"
    elif buttons and menus:
        layout_hint = "menu_or_toolbar"
    elif bullets and not unique_form_fields:
        layout_hint = "list_or_notes"
    elif links and not unique_form_fields:
        layout_hint = "link_or_reference"
    else:
        layout_hint = "document_or_chat"

    # Best-effort field state detection for simple "label: value" UIs.
    filled_fields = [f for f in unique_form_fields if f.get("state") == "filled"]
    empty_fields = [f for f in unique_form_fields if f.get("state") == "empty"]

    form_field_summary = []
    for field in unique_form_fields:
        if field["kind"] == "form_pair":
            form_field_summary.append(f"{field['label']}={field['value'] or '[empty]'}")
        else:
            form_field_summary.append(f"{field['label']}=[empty]")

    summary_bits = []
    if visible_points:
        summary_bits.append("可见关键信息: " + "、".join(visible_points))
    if layout_hint:
        summary_bits.append(f"UI类型: {layout_hint}")
    if unique_form_fields:
        summary_bits.append("表单字段: " + "、".join(form_field_summary[:8]))
    if buttons:
        summary_bits.append("按钮: " + "、".join(buttons[:8]))
    if menus:
        summary_bits.append("菜单/工具项: " + "、".join(menus[:8]))
    if links:
        summary_bits.append("链接: " + "、".join(links[:5]))
    if bullets:
        summary_bits.append("列表项: " + "；".join(bullets[:5]))
    if missing_labels:
        summary_bits.append("截图中这些字段看起来没有值: " + "、".join(missing_labels))
    if "OCR支持" in joined or "OCR方式" in joined:
        summary_bits.append("这是一张包含 OCR 说明文字的聊天截图，不要把文字内容误当成原始表单值")
    if not summary_bits:
        summary_bits.append("未发现明确结构化字段")

    if unique_form_fields:
        field_notes = []
        for field in unique_form_fields[:8]:
            if field["kind"] == "form_pair":
                field_notes.append(f"{field['label']}={field['value'] or '空'}")
            else:
                field_notes.append(f"{field['label']}=空")
        recommended_reply = (
            "我识别到这是一个"
            + layout_hint
            + "截图。"
            + ("表单字段包括：" + "、".join(field_notes) + "。" if field_notes else "")
            + ("按钮有：" + "、".join(buttons[:6]) + "。" if buttons else "")
            + ("菜单/工具项有：" + "、".join(menus[:6]) + "。" if menus else "")
            + ("链接有：" + "、".join(links[:4]) + "。" if links else "")
            + "如果你要我提取字段值、按钮含义或菜单结构，我可以按这个结构继续整理。"
        )
    elif visible_points:
        recommended_reply = (
            "我能确认截图里可见的信息有："
            + "、".join(visible_points)
            + "。"
            + "如果你是在问这些 OAuth 配置的实际值，截图里没有直接显示这些值，请把 "
            + "Client ID、Client Secret、Authorization URL、Token URL、Scopes "
            + "贴给我，我就能继续帮你完成配置。"
        )
    else:
        recommended_reply = "我已读取截图，但没有找到足够明确的字段和值，请再发一张更完整的截图或直接贴出相关字段内容。"

    return {
        "ui_analysis": {
            "layout_hint": layout_hint,
            "form_fields": unique_form_fields,
            "filled_fields": filled_fields,
            "empty_fields": empty_fields,
            "buttons": buttons,
            "menu_items": menus,
            "links": links,
            "bullets": bullets,
            "descriptions": descriptions,
            "noise": noise,
            "ordered_text": text_items,
        },
        "language_hint": language_hint,
        "visible_points": visible_points,
        "missing_labels": missing_labels,
        "detected_fields": detected_fields,
        "summary": "；".join(summary_bits),
        "recommended_reply": recommended_reply,
    }


def analyze_path(path: Path) -> Dict[str, Any]:
    path = _ensure_file(path)
    file_hash = _sha256_file(path)
    frames = _extract_frames(path)
    analyzed_frames: List[Dict[str, Any]] = []
    merged_text_parts: List[str] = []

    for frame in frames:
        ocr_input = _prepare_ocr_input(Path(frame["frame_path"]))
        ocr = _swift_ocr(ocr_input)
        text = (ocr.get("text") or "").strip()
        if text:
            merged_text_parts.append(text)
        analyzed_frames.append(
            {
                **frame,
                "text": text,
                "lines": ocr.get("lines", []),
                "language": ocr.get("language", ""),
            }
        )

    result = {
        "source_path": str(path),
        "source_hash": file_hash,
        "format": analyzed_frames[0]["format"] if analyzed_frames else "",
        "frame_count": len(analyzed_frames),
        "text": "\n\n".join(merged_text_parts).strip(),
        "frames": analyzed_frames,
    }
    result.update(_summarize_result(result))
    result["prompt"] = _build_prompt(result)
    return result


def ingest_payload(path: Optional[str], data_url: Optional[str], name: Optional[str]) -> Path:
    if path:
        return _ensure_file(Path(path)).resolve()
    if not data_url:
        raise BridgeError("either path or data_url is required")
    raw, mime = _decode_data_url(data_url)
    suffix_map = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/bmp": ".bmp",
        "image/tiff": ".tiff",
        "image/avif": ".avif",
        "application/pdf": ".pdf",
        "image/heic": ".heic",
        "image/heif": ".heif",
    }
    suffix = suffix_map.get(mime, Path(name or "image").suffix or ".bin")
    digest = _sha256_bytes(raw)
    out = WORK_DIR / f"{(name or 'image').rsplit('.', 1)[0]}-{digest[:16]}{suffix}"
    out.write_bytes(raw)
    return out


def resolve_image_input(
    path: Optional[str],
    data_url: Optional[str],
    name: Optional[str],
    source: Optional[str] = None,
) -> Path:
    normalized_source = (source or "auto").strip().lower()
    if normalized_source not in {"auto", "path", "data_url", "clipboard", "screenshot"}:
        raise BridgeError(f"unsupported source: {source}")

    if normalized_source == "path":
        if not path:
            raise BridgeError("source=path requires path")
        return _absolute_preserving_alias(_ensure_file(Path(path)))

    if normalized_source == "data_url":
        if not data_url:
            raise BridgeError("source=data_url requires data_url")
        return ingest_payload(None, data_url, name)

    if normalized_source == "clipboard":
        sources = _read_clipboard_sources()
        if not sources:
            raise BridgeError("clipboard does not contain a supported image/file")
        return sources[0]

    if normalized_source == "screenshot":
        screenshot = _latest_screenshot_file()
        if screenshot is None:
            raise BridgeError("no recent screenshot file found")
        return screenshot

    if path:
        return _absolute_preserving_alias(_ensure_file(Path(path)))
    if data_url:
        return ingest_payload(None, data_url, name)

    sources = _read_clipboard_sources()
    if sources:
        return sources[0]

    screenshot = _latest_screenshot_file()
    if screenshot is not None:
        return screenshot

    raise BridgeError("no image input found; provide path/data_url or copy an image to the clipboard")


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamp_slug() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def _safe_session_id(session_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", session_id):
        raise BridgeError(f"invalid image session id: {session_id}")
    return session_id


def _label_slug(label: Optional[str]) -> str:
    if not label:
        return "image-session"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", label.strip())[:40].strip("-")
    return slug or "image-session"


def _new_image_session_id(label: Optional[str]) -> str:
    token = hashlib.sha256(os.urandom(16)).hexdigest()[:8]
    return f"session-{_timestamp_slug()}-{_label_slug(label)}-{token}"


def _load_image_state_unlocked() -> Dict[str, Any]:
    if not IMAGE_STATE_PATH.exists():
        return {"active_session_id": None, "sessions": {}}
    try:
        state = json.loads(IMAGE_STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"active_session_id": None, "sessions": {}}
    if not isinstance(state.get("sessions"), dict):
        state["sessions"] = {}
    if "active_session_id" not in state:
        state["active_session_id"] = None
    return state


def _save_image_state_unlocked(state: Dict[str, Any]) -> None:
    IMAGE_INBOX_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = IMAGE_STATE_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(IMAGE_STATE_PATH)


def _ensure_image_session_unlocked(
    state: Dict[str, Any],
    session_id: Optional[str],
    label: Optional[str] = None,
) -> Dict[str, Any]:
    sessions = state.setdefault("sessions", {})
    if session_id:
        session_id = _safe_session_id(session_id)
    else:
        session_id = state.get("active_session_id") or _new_image_session_id(label)

    session = sessions.get(session_id)
    if not isinstance(session, dict):
        session_dir = IMAGE_INBOX_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        created_at = _now_iso()
        session = {
            "session_id": session_id,
            "label": label or "",
            "created_at": created_at,
            "updated_at": created_at,
            "directory": str(session_dir),
            "images": [],
        }
        sessions[session_id] = session
    else:
        Path(session.get("directory") or IMAGE_INBOX_DIR / session_id).mkdir(parents=True, exist_ok=True)
        if label and not session.get("label"):
            session["label"] = label
    state["active_session_id"] = session_id
    return session


def start_image_session(label: Optional[str] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
    with _IMAGE_STATE_LOCK:
        state = _load_image_state_unlocked()
        if session_id and session_id not in state.get("sessions", {}):
            raise BridgeError(f"image session not found: {session_id}")
        target_session_id = session_id or _new_image_session_id(label)
        session = _ensure_image_session_unlocked(state, target_session_id, label)
        session["updated_at"] = _now_iso()
        _save_image_state_unlocked(state)
        return _image_session_public(session, state)


def _image_meta(path: Path) -> Dict[str, Any]:
    try:
        with Image.open(path) as image:
            return {"size": list(image.size), "format": image.format or path.suffix.lstrip(".").upper()}
    except Exception:
        return {"size": [], "format": path.suffix.lstrip(".").upper()}


def _image_entry_public(entry: Dict[str, Any], index: Optional[int] = None) -> Dict[str, Any]:
    public = {
        "image_id": entry.get("image_id"),
        "index": index,
        "session_id": entry.get("session_id"),
        "path": entry.get("path"),
        "hash": entry.get("hash"),
        "created_at": entry.get("created_at"),
        "label": entry.get("label", ""),
        "source": entry.get("source", ""),
        "size": entry.get("size", []),
        "format": entry.get("format", ""),
        "consumed": bool(entry.get("consumed")),
    }
    return {key: value for key, value in public.items() if value is not None}


def _image_session_public(session: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    images = session.get("images") if isinstance(session.get("images"), list) else []
    return {
        "session_id": session.get("session_id"),
        "label": session.get("label", ""),
        "directory": session.get("directory"),
        "active": state.get("active_session_id") == session.get("session_id"),
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "image_count": len(images),
        "unconsumed_count": sum(1 for image in images if not image.get("consumed")),
    }


def capture_pasted_image(session_id: Optional[str] = None, label: Optional[str] = None) -> Dict[str, Any]:
    sources = _read_clipboard_sources()
    if not sources:
        raise BridgeError("clipboard does not contain a supported image/file")
    return store_pasted_image(sources[0], session_id=session_id, label=label, source="clipboard")


def store_pasted_image(
    source_path: Path,
    session_id: Optional[str] = None,
    label: Optional[str] = None,
    source: str = "clipboard",
) -> Dict[str, Any]:
    source_path = _ensure_file(source_path)
    digest = _sha256_file(source_path)
    with _IMAGE_STATE_LOCK:
        state = _load_image_state_unlocked()
        session = _ensure_image_session_unlocked(state, session_id, None)
        images = session.setdefault("images", [])
        for index, existing in enumerate(images, start=1):
            if existing.get("hash") == digest:
                if label and not existing.get("label"):
                    existing["label"] = label
                    session["updated_at"] = _now_iso()
                    _save_image_state_unlocked(state)
                return {
                    "session_id": session["session_id"],
                    "directory": session["directory"],
                    "duplicate": True,
                    "image": _image_entry_public(existing, index),
                }

        created_at = _now_iso()
        image_id = f"img-{_timestamp_slug()}-{digest[:10]}"
        suffix = source_path.suffix or ".bin"
        destination = Path(session["directory"]) / f"{len(images) + 1:04d}-{image_id}{suffix}"
        shutil.copy2(source_path, destination)
        meta = _image_meta(destination)
        entry = {
            "image_id": image_id,
            "session_id": session["session_id"],
            "path": str(destination),
            "hash": digest,
            "created_at": created_at,
            "label": label or "",
            "source": source,
            "original_path": str(source_path),
            "size": meta["size"],
            "format": meta["format"],
            "consumed": False,
        }
        images.append(entry)
        if len(images) > MAX_SESSION_IMAGES:
            removed = images[:-MAX_SESSION_IMAGES]
            session["images"] = images[-MAX_SESSION_IMAGES:]
            for old in removed:
                try:
                    Path(old.get("path", "")).unlink(missing_ok=True)
                except OSError:
                    pass
            images = session["images"]
        session["updated_at"] = created_at
        _save_image_state_unlocked(state)
        return {
            "session_id": session["session_id"],
            "directory": session["directory"],
            "duplicate": False,
            "image": _image_entry_public(entry, len(images)),
        }


def list_pasted_images(
    session_id: Optional[str] = None,
    include_consumed: bool = True,
    limit: int = 50,
) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 50), 100))
    with _IMAGE_STATE_LOCK:
        state = _load_image_state_unlocked()
        session = _ensure_image_session_unlocked(state, session_id, None)
        images = session.get("images") if isinstance(session.get("images"), list) else []
        public_images = [
            _image_entry_public(image, index)
            for index, image in enumerate(images, start=1)
            if include_consumed or not image.get("consumed")
        ][-limit:]
        _save_image_state_unlocked(state)
        return {
            **_image_session_public(session, state),
            "images": public_images,
        }


def _select_pasted_image_unlocked(
    session: Dict[str, Any],
    image_id: Optional[str],
    index: Optional[int],
    which: str,
) -> Tuple[Dict[str, Any], int]:
    images = session.get("images") if isinstance(session.get("images"), list) else []
    if not images:
        raise BridgeError(f"image session has no captured images: {session.get('session_id')}")

    if image_id:
        for position, image in enumerate(images, start=1):
            if image.get("image_id") == image_id:
                return image, position
        raise BridgeError(f"image not found in session: {image_id}")

    if index is not None:
        if index < 1 or index > len(images):
            raise BridgeError(f"image index out of range: {index}; available 1..{len(images)}")
        return images[index - 1], index

    normalized_which = (which or "latest_unconsumed").strip().lower()
    if normalized_which in {"latest_unconsumed", "unconsumed"}:
        for position in range(len(images), 0, -1):
            if not images[position - 1].get("consumed"):
                return images[position - 1], position
        return images[-1], len(images)
    if normalized_which == "latest":
        return images[-1], len(images)
    if normalized_which == "previous":
        if len(images) < 2:
            raise BridgeError("there is no previous image in this session")
        return images[-2], len(images) - 1
    raise BridgeError(f"unsupported image selector: {which}")


def analyze_pasted_image(
    session_id: Optional[str] = None,
    image_id: Optional[str] = None,
    index: Optional[int] = None,
    which: str = "latest_unconsumed",
    consume: bool = True,
    capture_current: bool = True,
) -> Dict[str, Any]:
    if capture_current:
        try:
            capture_pasted_image(session_id=session_id)
        except BridgeError:
            pass

    with _IMAGE_STATE_LOCK:
        state = _load_image_state_unlocked()
        session = _ensure_image_session_unlocked(state, session_id, None)
        image, position = _select_pasted_image_unlocked(session, image_id, index, which)
        image_path = Path(str(image.get("path", "")))
        selected_public = _image_entry_public(image, position)

    result = analyze_path(image_path)

    if consume:
        with _IMAGE_STATE_LOCK:
            state = _load_image_state_unlocked()
            session = _ensure_image_session_unlocked(state, session_id or selected_public["session_id"], None)
            image, position = _select_pasted_image_unlocked(session, selected_public["image_id"], None, "latest")
            image["consumed"] = True
            session["updated_at"] = _now_iso()
            selected_public = _image_entry_public(image, position)
            _save_image_state_unlocked(state)

    result["image_session"] = {
        "session_id": selected_public["session_id"],
        "selected_image": selected_public,
        "directory": str(Path(selected_public["path"]).parent),
    }
    return result


def _clipboard_watcher_loop() -> None:
    last_hash = ""
    while True:
        try:
            with _IMAGE_STATE_LOCK:
                state = _load_image_state_unlocked()
                active_session_id = state.get("active_session_id")
            if not active_session_id:
                time.sleep(CLIPBOARD_WATCH_INTERVAL_SECONDS)
                continue

            sources = _read_clipboard_sources()
            if sources:
                digest = _sha256_file(sources[0])
                if digest != last_hash:
                    store_pasted_image(sources[0], session_id=active_session_id, source="clipboard-watch")
                    last_hash = digest
        except Exception:
            pass
        time.sleep(CLIPBOARD_WATCH_INTERVAL_SECONDS)


def _start_clipboard_watcher() -> None:
    global _CLIPBOARD_WATCHER_STARTED
    if _CLIPBOARD_WATCHER_STARTED:
        return
    _CLIPBOARD_WATCHER_STARTED = True
    thread = threading.Thread(target=_clipboard_watcher_loop, name="clipboard-image-watch", daemon=True)
    thread.start()


def _claude_config_entry() -> Dict[str, Any]:
    return {
        "command": sys.executable,
        "args": [str(ROOT / "bridge.py"), "serve"],
    }


def install_claude_config() -> Dict[str, Any]:
    CLAUDE_APP_SUPPORT.mkdir(parents=True, exist_ok=True)
    config: Dict[str, Any] = {}
    if CLAUDE_CONFIG_PATH.exists():
        try:
            config = json.loads(CLAUDE_CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise BridgeError(f"Claude config is not valid JSON: {CLAUDE_CONFIG_PATH}") from exc

    mcp_servers = config.get("mcpServers")
    if not isinstance(mcp_servers, dict):
        mcp_servers = {}

    mcp_servers["claude-image-bridge"] = _claude_config_entry()
    config["mcpServers"] = mcp_servers

    backup_path = None
    if CLAUDE_CONFIG_PATH.exists():
        backup_path = CLAUDE_CONFIG_PATH.with_name(
            f"{CLAUDE_CONFIG_PATH.name}.bak-{_timestamp_slug()}"
        )
        backup_path.write_text(CLAUDE_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    tmp_path = CLAUDE_CONFIG_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(CLAUDE_CONFIG_PATH)

    return {
        "config_path": str(CLAUDE_CONFIG_PATH),
        "backup_path": str(backup_path) if backup_path else None,
        "server_name": "claude-image-bridge",
    }


def _tool_schemas() -> List[Dict[str, Any]]:
    return [
        {
            "name": "analyze_image",
            "description": "Normalize an image, run OCR on each frame/page, and return structured Chinese/English text plus a concise summary. When path/data_url are omitted, it automatically falls back to clipboard and recent screenshots.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute local path to an image or document."},
                    "data_url": {"type": "string", "description": "Base64 data URL for an image or PDF."},
                    "name": {"type": "string", "description": "Optional filename hint for data_url inputs."},
                    "source": {
                        "type": "string",
                        "enum": ["auto", "path", "data_url", "clipboard", "screenshot"],
                        "description": "Where to resolve the image from when path/data_url are omitted.",
                    },
                },
            },
        },
        {
            "name": "extract_text_from_image",
            "description": "Alias of analyze_image for a shorter text-only workflow, with the same clipboard and recent-screenshot fallback.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "data_url": {"type": "string"},
                    "name": {"type": "string"},
                    "source": {
                        "type": "string",
                        "enum": ["auto", "path", "data_url", "clipboard", "screenshot"],
                    },
                },
            },
        },
        {
            "name": "normalize_image",
            "description": "Convert an image into a normalized PNG frame sequence and return frame metadata, with the same auto resolution behavior as analyze_image.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "data_url": {"type": "string"},
                    "name": {"type": "string"},
                    "source": {
                        "type": "string",
                        "enum": ["auto", "path", "data_url", "clipboard", "screenshot"],
                    },
                },
            },
        },
        {
            "name": "analyze_clipboard_image",
            "description": "Analyze the current macOS clipboard image or copied file without providing a path.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "analyze_recent_screenshot",
            "description": "Analyze the newest screenshot saved on the Mac, useful for system shortcut screenshots that land on disk.",
            "inputSchema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "start_image_session",
            "description": "Create or resume an explicit image session for the current Claude conversation. Use this before handling pasted images so later images are saved under a stable session directory.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "description": "Optional human-readable label for this conversation."},
                    "session_id": {"type": "string", "description": "Existing bridge image session id to resume."},
                },
            },
        },
        {
            "name": "capture_pasted_image",
            "description": "Save the current macOS clipboard image/file into the active or specified image session directory, with hash deduplication.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Bridge image session id returned by start_image_session."},
                    "label": {"type": "string", "description": "Optional note for the captured image."},
                },
            },
        },
        {
            "name": "list_pasted_images",
            "description": "List images captured for an image session, including stable image_id, 1-based index, timestamp, path, size, and consumed state. Use this when the user asks about an earlier pasted image.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Bridge image session id returned by start_image_session."},
                    "include_consumed": {"type": "boolean", "description": "Whether to include images already analyzed."},
                    "limit": {"type": "number", "description": "Maximum number of images to return, up to 100."},
                },
            },
        },
        {
            "name": "analyze_pasted_image",
            "description": "Analyze a pasted image from an image session by image_id, 1-based index, latest, previous, or latest unconsumed. By default it first captures the current clipboard into the session.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Bridge image session id returned by start_image_session."},
                    "image_id": {"type": "string", "description": "Stable image id from list_pasted_images."},
                    "index": {"type": "number", "description": "1-based index from list_pasted_images."},
                    "which": {
                        "type": "string",
                        "enum": ["latest_unconsumed", "latest", "previous"],
                        "description": "Selector used when image_id/index are omitted.",
                    },
                    "consume": {"type": "boolean", "description": "Mark the selected image as consumed after analysis."},
                    "capture_current": {"type": "boolean", "description": "Capture current clipboard into the session before selecting an image."},
                },
            },
        },
    ]


def _mcp_ok(result: Any) -> Dict[str, Any]:
    return {"result": result}


def _mcp_error(code: int, message: str, data: Optional[Any] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        payload["data"] = data
    return {"error": payload}


def _text_content(text: str) -> List[Dict[str, str]]:
    return [{"type": "text", "text": text}]


def _tool_response(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if tool_name == "start_image_session":
        result = start_image_session(args.get("label"), args.get("session_id"))
        return {
            "content": _text_content(json.dumps(result, ensure_ascii=False, indent=2)),
            "isError": False,
        }
    if tool_name == "capture_pasted_image":
        result = capture_pasted_image(args.get("session_id"), args.get("label"))
        return {
            "content": _text_content(json.dumps(result, ensure_ascii=False, indent=2)),
            "isError": False,
        }
    if tool_name == "list_pasted_images":
        result = list_pasted_images(
            args.get("session_id"),
            bool(args.get("include_consumed", True)),
            int(args.get("limit", 50) or 50),
        )
        return {
            "content": _text_content(json.dumps(result, ensure_ascii=False, indent=2)),
            "isError": False,
        }
    if tool_name == "analyze_pasted_image":
        result = analyze_pasted_image(
            session_id=args.get("session_id"),
            image_id=args.get("image_id"),
            index=int(args["index"]) if args.get("index") is not None else None,
            which=args.get("which") or "latest_unconsumed",
            consume=bool(args.get("consume", True)),
            capture_current=bool(args.get("capture_current", True)),
        )
        return {
            "content": _text_content(json.dumps(result, ensure_ascii=False, indent=2)),
            "isError": False,
        }
    if tool_name in {"analyze_clipboard_image", "analyze_recent_screenshot"}:
        source_mode = "clipboard" if tool_name == "analyze_clipboard_image" else "screenshot"
        source = resolve_image_input(None, None, None, source_mode)
        result = analyze_path(source)
        return {
            "content": _text_content(json.dumps(result, ensure_ascii=False, indent=2)),
            "isError": False,
        }
    source = resolve_image_input(
        args.get("path"),
        args.get("data_url"),
        args.get("name"),
        args.get("source"),
    )
    if tool_name in {"analyze_image", "extract_text_from_image"}:
        result = analyze_path(source)
        return {
            "content": _text_content(json.dumps(result, ensure_ascii=False, indent=2)),
            "isError": False,
        }
    if tool_name == "normalize_image":
        result = {
            "source_path": str(source),
            "frames": _extract_frames(source),
        }
        return {
            "content": _text_content(json.dumps(result, ensure_ascii=False, indent=2)),
            "isError": False,
        }
    return {
        "content": _text_content(f"Unknown tool: {tool_name}"),
        "isError": True,
    }


def _handle_request(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    method = payload.get("method")
    req_id = payload.get("id")
    params = payload.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "claude-image-bridge", "version": "0.1.0"},
            },
        }

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": _tool_schemas()},
        }

    if method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments") or {}
        if tool_name not in {
            "analyze_image",
            "extract_text_from_image",
            "normalize_image",
            "analyze_clipboard_image",
            "analyze_recent_screenshot",
            "start_image_session",
            "capture_pasted_image",
            "list_pasted_images",
            "analyze_pasted_image",
        }:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }
        try:
            result = _tool_response(tool_name, args)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": _text_content(str(exc)),
                    "isError": True,
                },
            }

    if req_id is None:
        return None

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def _read_message(stream) -> Optional[Tuple[Dict[str, Any], str]]:
    first_line = stream.readline()
    while first_line and not first_line.strip():
        first_line = stream.readline()
    if not first_line:
        return None

    stripped = first_line.strip()
    if stripped.startswith(b"{"):
        return json.loads(stripped.decode("utf-8")), "jsonl"

    headers: Dict[str, str] = {}
    line = first_line.decode("utf-8", errors="replace").strip()
    if ":" in line:
        key, value = line.split(":", 1)
        headers[key.lower().strip()] = value.strip()

    while True:
        line_bytes = stream.readline()
        if not line_bytes:
            return None
        line = line_bytes.decode("utf-8", errors="replace").strip()
        if not line:
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.lower().strip()] = value.strip()

    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = stream.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8")), "headers"


def _write_message(stream, message: Dict[str, Any], framing: str) -> None:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    if framing == "jsonl":
        stream.write(body + b"\n")
    else:
        stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8"))
        stream.write(body)
    stream.flush()


def serve_stdio() -> None:
    _start_clipboard_watcher()
    while True:
        message = _read_message(sys.stdin.buffer)
        if message is None:
            return
        payload, framing = message
        response = _handle_request(payload)
        if response is not None:
            _write_message(sys.stdout.buffer, response, framing)


def self_test() -> int:
    sample = WORK_DIR / "self-test.png"
    image = Image.new("RGB", (900, 260), "white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 60), "CLAUDE IMAGE BRIDGE", fill="black")
    draw.text((40, 140), "hello 123", fill="black")
    image.save(sample)
    result = analyze_path(sample)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def install_and_report() -> int:
    result = install_claude_config()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="Claude Desktop image bridge")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="Analyze a local file path")
    analyze.add_argument("path", help="Absolute or relative image path")

    serve = sub.add_parser("serve", help="Run an MCP server over stdio")

    sub.add_parser("install", help="Write Claude Desktop MCP config")

    sub.add_parser("self-test", help="Create a sample image and verify OCR")

    args = parser.parse_args(argv)

    if args.command == "analyze":
        result = analyze_path(_absolute_preserving_alias(Path(args.path)))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.command == "serve":
        serve_stdio()
        return 0

    if args.command == "install":
        return install_and_report()

    if args.command == "self-test":
        return self_test()

    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
