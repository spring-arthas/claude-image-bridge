from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProjectHardeningTests(unittest.TestCase):
    def test_install_script_requires_explicit_config_when_claude_configs_are_ambiguous(self) -> None:
        install_script = (ROOT / "scripts" / "install_mac.sh").read_text(encoding="utf-8")

        self.assertIn("Multiple Claude Desktop config files", install_script)
        self.assertIn("CLAUDE_IMAGE_BRIDGE_CONFIG", install_script)

    def test_doctor_skips_python_import_check_when_python3_is_missing(self) -> None:
        doctor_script = (ROOT / "scripts" / "doctor_mac.sh").read_text(encoding="utf-8")

        self.assertIn("Skipping Python import check", doctor_script)
        self.assertIn("command -v python3", doctor_script)

    def test_audit_script_masks_secret_values(self) -> None:
        audit_script = ROOT / "scripts" / "audit_claude_mac.py"
        self.assertTrue(audit_script.exists())

        with tempfile.TemporaryDirectory() as home_dir:
            home = Path(home_dir)
            config_dir = home / "Library/Application Support/Claude-3p"
            config_dir.mkdir(parents=True)
            (config_dir / "claude_desktop_config.json").write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "existing": {
                                "command": "server",
                                "env": {"apiKey": "super-secret-value"},
                            }
                        },
                        "deepseek": {"token": "deepseek-token-value"},
                    }
                ),
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["HOME"] = str(home)
            result = subprocess.run(
                [sys.executable, str(audit_script)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("<masked>", result.stdout)
        self.assertNotIn("super-secret-value", result.stdout)
        self.assertNotIn("deepseek-token-value", result.stdout)

    def test_smoke_test_requires_explicit_clipboard_overwrite_opt_in(self) -> None:
        smoke_test = (ROOT / "mcp_smoke_test.py").read_text(encoding="utf-8")

        self.assertIn("--allow-clipboard-overwrite", smoke_test)
        self.assertIn("CLAUDE_IMAGE_BRIDGE_ALLOW_CLIPBOARD_SMOKE", smoke_test)

    def test_clipboard_watcher_can_be_disabled_and_is_documented(self) -> None:
        bridge = (ROOT / "bridge.py").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        task = (ROOT / "TASK_MAC_CLAUDE_DESKTOP_DEEPSEEK_IMAGE_BRIDGE.md").read_text(encoding="utf-8")

        self.assertIn("CLAUDE_IMAGE_BRIDGE_DISABLE_CLIPBOARD_WATCH", bridge)
        self.assertIn("CLAUDE_IMAGE_BRIDGE_DISABLE_CLIPBOARD_WATCH", readme)
        self.assertIn("CLAUDE_IMAGE_BRIDGE_DISABLE_CLIPBOARD_WATCH", task)


if __name__ == "__main__":
    unittest.main()
