"""Install a built wheel and exercise its CLI in an isolated user environment."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from agentsync.jsonutil import Json, JsonObject


class InstalledSmoke:
    """Cross-platform installed-package acceptance without real harness writes."""

    def __init__(self, root: Path, wheel: Path) -> None:
        self.root = root
        wheels = tuple(wheel.glob("*.whl")) if wheel.is_dir() else (wheel,)
        if len(wheels) != 1:
            raise ValueError("Expected exactly one built wheel")
        self.wheel = wheels[0].resolve()
        self.environment = dict(os.environ)
        self.environment.pop("PYTHONPATH", None)
        for key, folder in (
            ("HOME", "home"),
            ("USERPROFILE", "home"),
            ("XDG_CONFIG_HOME", "config"),
            ("XDG_DATA_HOME", "data"),
            ("XDG_STATE_HOME", "state"),
            ("XDG_CACHE_HOME", "cache"),
            ("UV_TOOL_DIR", "tools"),
            ("UV_TOOL_BIN_DIR", "bin"),
        ):
            self.environment[key] = str(root / folder)
        (root / "home").mkdir()
        self.executable = (
            root / "bin" / ("agentsync.exe" if os.name == "nt" else "agentsync")
        )
        self.checks: list[str] = []

    def command(self, *arguments: str) -> JsonObject:
        """Execute only the installed wrapper and require valid successful JSON."""
        result = self._process([str(self.executable), *arguments, "--json"])
        report = Json.object(Json.loads(result.stdout.decode()))
        if report.get("ok") is False:
            raise RuntimeError(f"Installed command blocked: {arguments}")
        self.checks.append(" ".join(arguments))
        return report

    def run(self) -> JsonObject:
        """Verify bootstrap, read-only planning, convergence, and packaged contracts."""
        self._process(
            [
                "uv",
                "tool",
                "install",
                "--python",
                sys.executable,
                "--from",
                str(self.wheel),
                "agentsync",
            ]
        )
        self.command("init")
        file = self.root / "config/agentsync/config.json"
        data = Json.object(Json.loads(file.read_text(encoding="utf-8")))
        source = self.root / "config/agentsync/customizations/instructions/rule.md"
        target = self.root / "target/instructions/rule/rule.md"
        source_name = next(iter(Json.object(data["sources"])))
        data["destinations"] = {
            "target": {"location": str(self.root / "target"), "enabled": True}
        }
        data["routes"] = [
            {"name": "all", "sources": [source_name], "destinations": ["target"]}
        ]
        file.write_text(Json.dumps(data), encoding="utf-8")
        source.write_bytes(b"first")
        self.command("validate")
        self.command("plan")
        if target.exists():
            raise RuntimeError("Read-only planning wrote a destination")
        self.command("sync")
        self._content(target, b"first")
        source.write_bytes(b"second")
        self.command("sync")
        self._content(target, b"second")
        target.write_bytes(b"drift")
        self.command("watch", "--once")
        self._content(target, b"second")
        self.command("status")
        self.command("explain", "rule")
        self.command("contracts", "list")
        source.unlink()
        self.command("sync")
        if target.exists():
            raise RuntimeError("Confirmed source deletion did not converge")
        return {
            "version": 1,
            "ok": True,
            "platform": sys.platform,
            "checks": list(self.checks),
        }

    def _process(self, command: list[str]) -> subprocess.CompletedProcess[bytes]:
        """Bound fixed-argv subprocesses and preserve useful failure diagnostics."""
        return subprocess.run(  # noqa: S603 - explicit isolated installation/CLI argv
            command,
            env=self.environment,
            cwd=self.root,
            capture_output=True,
            check=True,
            timeout=180,
        )

    @staticmethod
    def _content(path: Path, expected: bytes) -> None:
        """Verify actual destination bytes rather than success text."""
        if path.read_bytes() != expected:
            raise RuntimeError(f"Installed reconciliation mismatch: {path}")

    @classmethod
    def main(cls) -> None:
        """Expose the isolated smoke to all platform CI jobs."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--wheel", type=Path, required=True)
        parser.add_argument("--output", type=Path, required=True)
        arguments = parser.parse_args()
        try:
            with tempfile.TemporaryDirectory(
                prefix="agentsync-installed-"
            ) as directory:
                report = cls(Path(directory), arguments.wheel).run()
        except subprocess.CalledProcessError as error:
            sys.stderr.write(error.stderr.decode(errors="replace"))
            raise SystemExit(error.returncode) from error
        output = Path(arguments.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(Json.dumps(report), encoding="utf-8")
        sys.stdout.write(Json.dumps(report))


if __name__ == "__main__":
    InstalledSmoke.main()
