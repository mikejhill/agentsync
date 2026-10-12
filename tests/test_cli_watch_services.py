"""CLI UX, scheduler exits, watcher timing, and native startup contracts."""

from __future__ import annotations

import json
import plistlib
import subprocess
import sys
from typing import override

import pytest
from tests.conftest import Sandbox

from agentsync.__main__ import Application
from agentsync.cli import CommandLine
from agentsync.engine import Engine
from agentsync.exceptions import AppError
from agentsync.jsonutil import JsonObject
from agentsync.services import ServiceManager
from agentsync.watch import WatchCoordinator


class TestCLI:
    """Human and machine interfaces exercise public entry points."""

    @pytest.mark.parametrize(
        "name",
        ["validate", "plan", "status", "explain"],
        ids=["validate", "plan", "status", "explain"],
    )
    def test_read_only_commands_do_not_bootstrap(
        self, sandbox: Sandbox, name: str
    ) -> None:
        """Read-only commands cannot initialize an unknown configuration."""
        code = Application().run([name, "--json"])
        assert code == (0 if name == "status" else 2)
        assert not sandbox.paths.config.exists()

    def test_default_bootstrap_and_status(
        self, sandbox: Sandbox, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Sync initializes disabled templates and reports machine-readable status."""
        assert Application().run(["sync", "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["applied"]
        assert sandbox.paths.config.exists()
        assert Application().run(["status", "--json"]) == 0
        assert json.loads(capsys.readouterr().out)["ok"] is True

    def test_explicit_missing_config(self, sandbox: Sandbox) -> None:
        """Explicit config suppresses default bootstrap."""
        assert (
            Application().run(["sync", "--config-file", str(sandbox.root / "missing")])
            == 2
        )
        assert not sandbox.paths.config.exists()

    def test_human_operations_and_explain(
        self, sandbox: Sandbox, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Human results show operations and explain preserves provenance."""
        settings = sandbox.config()
        sandbox.put("instructions/rule.md")
        args = ["--config-file", str(settings.file)]
        assert Application().run(["plan", *args]) == 0
        assert "create" in capsys.readouterr().out
        assert Application().run(["explain", "rule", *args, "--json"]) == 0
        assert "route:default" in capsys.readouterr().out
        assert Application().run(["sync", *args]) == 0
        assert "OK target" in capsys.readouterr().out

    def test_failure_and_adoption_exit_codes(
        self, sandbox: Sandbox, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Operational conflicts return one and explicit adoption resolves them."""
        settings = sandbox.config()
        sandbox.put("instructions/rule.md")
        file = sandbox.root / "target/instructions/rule/rule.md"
        file.parent.mkdir(parents=True)
        file.write_bytes(b"unmanaged")
        args = ["--config-file", str(settings.file)]
        assert Application().run(["sync", *args]) == 1
        assert "BLOCKED" in capsys.readouterr().out
        assert Application().run(["adopt", *args]) == 0

    def test_contracts_and_init(self, sandbox: Sandbox) -> None:
        """Contract inspection does not need user distribution configuration."""
        assert Application().run(["contracts", "list", "--json"]) == 0
        assert Application().run(["contracts", "show", "codex", "--json"]) == 0
        assert Application().run(["init"]) == 0
        assert (
            Application().run(["init", "--config-file", str(sandbox.root / "config")])
            == 2
        )

    def test_watch_once_and_validation(self, sandbox: Sandbox) -> None:
        """Watcher initialization uses exactly the manual sync engine."""
        settings = sandbox.config()
        sandbox.put("instructions/rule.md")
        assert Application().run(["validate", "--config-file", str(settings.file)]) == 0
        assert (
            Application().run(["watch", "--once", "--config-file", str(settings.file)])
            == 0
        )

    def test_usage_help_and_argument_types(self) -> None:
        """Help and usage failures use argparse conventions."""
        with pytest.raises(SystemExit) as help_exit:
            CommandLine().parse(["--help"])
        assert help_exit.value.code == 0
        with pytest.raises(SystemExit) as usage_exit:
            CommandLine().parse(["unknown"])
        assert usage_exit.value.code == 2
        command = CommandLine().parse(
            ["sync", "--target", "one", "--target", "two", "-v"]
        )
        assert command.targets == ("one", "two")
        assert command.verbose

    def test_installed_module_entrypoint(self) -> None:
        """A real subprocess executes the installed distribution entry point."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "agentsync",
                "contracts",
                "show",
                "claude",
                "--json",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert json.loads(result.stdout)["profile"] == "claude"


class RecordingEngine(Engine):
    """Injected deterministic engine records watcher trigger decisions."""

    def __init__(self, sandbox: Sandbox) -> None:
        super().__init__(sandbox.paths)
        self.fetches: list[bool] = []
        self.succeed = True

    @override
    def run(
        self,
        settings: object,
        targets: tuple[str, ...] = (),
        *,
        apply: bool = False,
        adopt: bool = False,
        fetch: bool = True,
    ) -> JsonObject:
        """Record invocation without filesystem activity."""
        self.fetches.append(fetch)
        return {"version": 1, "ok": self.succeed}


class TestWatchCoordinator:
    """Virtual-time tests cover debounce, polls, retries, and config reload."""

    def test_events_and_periodic_remote_poll(self, sandbox: Sandbox) -> None:
        """Debounced events reconcile locally between remote polling deadlines."""
        settings = sandbox.config()
        engine = RecordingEngine(sandbox)
        watcher = WatchCoordinator(sandbox.paths, settings.file, engine=engine)
        assert watcher.tick(0) is not None
        assert watcher.tick(1, event=True) is None
        assert watcher.tick(1.6) is not None
        assert engine.fetches == [True, False]
        assert watcher.tick(61.6) is not None
        assert watcher.tick(301) is not None
        assert engine.fetches[-1]

    def test_invalid_config_retains_last_valid_policy(self, sandbox: Sandbox) -> None:
        """Incomplete editor saves do not erase destination policy."""
        settings = sandbox.config()
        watcher = WatchCoordinator(
            sandbox.paths, settings.file, engine=RecordingEngine(sandbox)
        )
        watcher.tick(0)
        settings.file.write_text("{", encoding="utf-8")
        assert watcher.tick(61) is not None
        assert watcher.settings == settings

    def test_retry_backoff(self, sandbox: Sandbox) -> None:
        """Repeated failures wait without discarding desired state."""
        settings = sandbox.config()
        engine = RecordingEngine(sandbox)
        engine.succeed = False
        watcher = WatchCoordinator(sandbox.paths, settings.file, engine=engine)
        watcher.tick(0)
        watcher.tick(0.1, event=True)
        assert watcher.tick(0.7) is None
        assert watcher.tick(2) is not None


class TestServiceManager:
    """Cross-platform native definitions are inspectable without installation."""

    @pytest.mark.parametrize(
        "platform", ["win32", "darwin", "linux"], ids=["windows", "macos", "linux"]
    )
    def test_native_definition_contains_explicit_config(
        self, sandbox: Sandbox, platform: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Login definitions invoke the installed interpreter and explicit config."""
        monkeypatch.setattr("shutil.which", self._systemctl)
        manager = ServiceManager(
            sandbox.paths, sandbox.root / "with spaces/config.json", platform=platform
        )
        definition = manager.definition()
        text = definition.content.decode("utf-16" if platform == "win32" else "utf-8")
        assert "agentsync" in text
        assert "--config-file" in text
        if platform == "win32":
            assert "Hidden>true" in text
            assert "LeastPrivilege" in text
        if platform == "darwin":
            assert plistlib.loads(definition.content)["RunAtLoad"]
        assert not definition.path.exists()

    def test_desktop_fallback_and_lifecycle(
        self, sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fallback installs and removes only its own autostart entry."""
        monkeypatch.setattr("shutil.which", self._absent)
        manager = ServiceManager(
            sandbox.paths, sandbox.root / "config.json", platform="linux"
        )
        assert manager.execute("status")["installed"] is False
        manager.execute("install")
        assert manager.execute("status")["installed"] is True
        with pytest.raises(AppError, match="next login"):
            manager.execute("start")
        manager.execute("uninstall")
        assert manager.execute("status")["installed"] is False
        manager.execute("uninstall")

    def test_uninstalled_start_and_bad_action(self, sandbox: Sandbox) -> None:
        """Missing startup configuration and unknown actions are errors."""
        manager = ServiceManager(
            sandbox.paths, sandbox.root / "config.json", platform="win32"
        )
        with pytest.raises(AppError, match="not installed"):
            manager.execute("start")
        with pytest.raises(AppError, match="Unknown"):
            manager.execute("unknown")

    @staticmethod
    def _systemctl(name: str) -> str | None:
        """Return a simulated systemd executable."""
        return "/usr/bin/systemctl" if name == "systemctl" else None

    @staticmethod
    def _absent(_name: str) -> None:
        """Simulate a desktop without systemd."""
        return
