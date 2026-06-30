#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import base64
import argparse
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PYTHON = Path(os.environ.get("PYTHON", sys.executable))
SWIFT_CACHE = Path("/private/tmp/swift-module-cache")


def write_message(proc, payload):
    body = json.dumps(payload).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
    proc.stdin.write(header + body)
    proc.stdin.flush()


def read_message(proc):
    headers = {}
    while True:
        line = proc.stdout.readline().decode("utf-8")
        if not line.strip():
            break
        key, value = line.split(":", 1)
        headers[key.lower().strip()] = value.strip()
    length = int(headers["content-length"])
    body = proc.stdout.read(length)
    return json.loads(body.decode("utf-8"))


def write_jsonl_message(proc, payload):
    proc.stdin.write(json.dumps(payload).encode("utf-8") + b"\n")
    proc.stdin.flush()


def read_jsonl_message(proc):
    return json.loads(proc.stdout.readline().decode("utf-8"))


def assert_tool_success(response, tool_name):
    assert "result" in response, response
    assert response["result"].get("isError") is False, f"{tool_name} failed: {response}"
    assert response["result"].get("content"), response
    return json.loads(response["result"]["content"][0]["text"])


def clipboard_overwrite_allowed(argv):
    parser = argparse.ArgumentParser(description="Smoke test claude-image-bridge MCP tools.")
    parser.add_argument(
        "--allow-clipboard-overwrite",
        action="store_true",
        help="Allow this test to clear and replace the current macOS clipboard with a generated test image.",
    )
    args = parser.parse_args(argv)
    return args.allow_clipboard_overwrite or os.environ.get("CLAUDE_IMAGE_BRIDGE_ALLOW_CLIPBOARD_SMOKE") == "1"


def main(argv=None) -> int:
    if not clipboard_overwrite_allowed(sys.argv[1:] if argv is None else argv):
        print(
            "Refusing to run clipboard smoke test because it overwrites the current macOS clipboard. "
            "Rerun with --allow-clipboard-overwrite or set CLAUDE_IMAGE_BRIDGE_ALLOW_CLIPBOARD_SMOKE=1.",
            file=sys.stderr,
        )
        return 2

    proc = subprocess.Popen(
        [str(PYTHON), str(ROOT / "bridge.py"), "serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        write_message(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke-test", "version": "0.1"},
                },
            },
        )
        init = read_message(proc)

        write_message(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        write_message(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = read_message(proc)

        from PIL import Image, ImageDraw

        image = Image.new("RGB", (640, 180), "white")
        draw = ImageDraw.Draw(image)
        draw.text((32, 48), "MCP TOOL SMOKE TEST", fill="black")
        draw.text((32, 108), "abc 123", fill="black")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        data_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

        write_message(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "analyze_image",
                    "arguments": {"data_url": data_url, "name": "smoke.png"},
                },
            },
        )
        call = read_message(proc)

        clipboard_image = Image.new("RGB", (520, 160), "white")
        clipboard_draw = ImageDraw.Draw(clipboard_image)
        clipboard_draw.text((24, 36), "CLIPBOARD SMOKE", fill="black")
        clipboard_draw.text((24, 92), "中文 clipboard 123", fill="black")
        clipboard_file = Path("/private/tmp/claude-image-bridge-clipboard-test.png")
        clipboard_image.save(clipboard_file)

        swift_code = f'''
import AppKit
import Foundation

let path = CommandLine.arguments[1]
guard let image = NSImage(contentsOfFile: path) else {{
    fputs("failed to load image\\n", stderr)
    exit(1)
}}
let pb = NSPasteboard.general
pb.clearContents()
if !pb.writeObjects([image]) {{
    fputs("failed to write clipboard\\n", stderr)
    exit(1)
}}
print("ok")
'''
        subprocess.run(
            [
                "swift",
                "-module-cache-path",
                str(SWIFT_CACHE),
                "-e",
                swift_code,
                str(clipboard_file),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        write_message(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "analyze_clipboard_image",
                    "arguments": {},
                },
            },
        )
        clipboard_call = read_message(proc)

        write_message(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "analyze_image",
                    "arguments": {},
                },
            },
        )
        auto_clipboard_call = read_message(proc)

        write_message(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {
                    "name": "start_image_session",
                    "arguments": {"label": "smoke-session"},
                },
            },
        )
        image_session_call = read_message(proc)
        image_session = assert_tool_success(image_session_call, "start_image_session")
        session_id = image_session["session_id"]

        write_message(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "capture_pasted_image",
                    "arguments": {"session_id": session_id, "label": "first clipboard smoke"},
                },
            },
        )
        capture_call = read_message(proc)
        capture = assert_tool_success(capture_call, "capture_pasted_image")
        assert capture["session_id"] == session_id
        assert capture["image"]["image_id"]

        write_message(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {
                    "name": "list_pasted_images",
                    "arguments": {"session_id": session_id},
                },
            },
        )
        list_call = read_message(proc)
        listed = assert_tool_success(list_call, "list_pasted_images")
        assert listed["session_id"] == session_id
        assert len(listed["images"]) >= 1

        write_message(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {
                    "name": "analyze_pasted_image",
                    "arguments": {"session_id": session_id, "index": 1, "consume": True},
                },
            },
        )
        pasted_analysis_call = read_message(proc)
        pasted_analysis = assert_tool_success(pasted_analysis_call, "analyze_pasted_image")
        assert pasted_analysis["image_session"]["session_id"] == session_id
        assert pasted_analysis["image_session"]["selected_image"]["image_id"] == listed["images"][0]["image_id"]

        jsonl_proc = subprocess.Popen(
            [str(PYTHON), str(ROOT / "bridge.py"), "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            write_jsonl_message(
                jsonl_proc,
                {
                    "jsonrpc": "2.0",
                    "id": 10,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "jsonl-smoke-test", "version": "0.1"},
                    },
                },
            )
            jsonl_init = read_jsonl_message(jsonl_proc)
            write_jsonl_message(jsonl_proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
            write_jsonl_message(jsonl_proc, {"jsonrpc": "2.0", "id": 11, "method": "tools/list", "params": {}})
            jsonl_tools = read_jsonl_message(jsonl_proc)
        finally:
            jsonl_proc.terminate()

        print(
            json.dumps(
                {
                    "initialize": init,
                    "tools": tools,
                    "call": call,
                    "clipboard_call": clipboard_call,
                    "auto_clipboard_call": auto_clipboard_call,
                    "image_session_call": image_session_call,
                    "capture_call": capture_call,
                    "list_call": list_call,
                    "pasted_analysis_call": pasted_analysis_call,
                    "jsonl_initialize": jsonl_init,
                    "jsonl_tools": jsonl_tools,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
