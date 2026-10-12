"""Concurrent CLI runs, ownership commit failures, and recoverable rollback failures."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import override

import pytest
from tests.conftest import Sandbox

from agentsync.__main__ import Application
from agentsync.exceptions import TransactionError
from agentsync.jsonutil import Json
from agentsync.models import Operation, Output
from agentsync.state import OwnershipStore
from agentsync.transactions import TransactionManager


class FailingOwnership(OwnershipStore):
    """Fail ownership once after file writes, then allow rollback state restoration."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.calls = 0

    @override
    def replace(
        self, owner: str, targets: set[str], outputs: tuple[Output, ...]
    ) -> None:
        """Simulate a failed SQLite commit with an available recovery path."""
        self.calls += 1
        if self.calls == 1:
            raise sqlite3.OperationalError("injected commit failure")
        super().replace(owner, targets, outputs)


class TestRuntimeFailures:
    """Failures retain recoverable state and scheduler-friendly diagnostics."""

    def test_ownership_commit_failure_rolls_back_files(self, sandbox: Sandbox) -> None:
        """SQLite failure cannot leave a generated file reported as success."""
        path = sandbox.root / "target.bin"
        store = FailingOwnership(sandbox.paths.state)
        manager = TransactionManager(store)
        with pytest.raises(TransactionError, match="rolled back"):
            manager.apply(
                "owner",
                {"target"},
                (Operation(path, None, b"new"),),
                (Output(path, b"new", "target", ()),),
            )
        assert not path.exists()
        assert store.records() == {}
        assert not manager.journal.exists()

    def test_journal_removal_failure_is_recoverable(
        self, sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rollback failure retains its journal and later recovery converges."""
        path = sandbox.root / "file"
        path.write_bytes(b"old")
        store = OwnershipStore(sandbox.paths.state)
        manager = TransactionManager(store)
        original = Path.unlink
        with monkeypatch.context() as patch:
            patch.setattr(Path, "unlink", self._locked_unlink)
            with pytest.raises(TransactionError, match="Recovery failed"):
                manager.apply(
                    "owner",
                    {"target"},
                    (Operation(path, b"old", b"new"),),
                    (Output(path, b"new", "target", ()),),
                )
        assert Path.unlink is original
        assert manager.journal.exists()
        assert path.read_bytes() == b"old"
        manager.recover()
        assert not manager.journal.exists()

    @staticmethod
    def _locked_unlink(path: Path, *, missing_ok: bool = False) -> None:
        """Lock only journal deletion; staged files remain removable."""
        if path.name == "transaction.json":
            raise PermissionError("injected locked journal")
        try:
            os.unlink(path)  # noqa: PTH108 - bypass the injected Path.unlink fault
        except FileNotFoundError:
            if not missing_ok:
                raise

    def test_corrupt_ownership_database_returns_operational_exit(
        self, sandbox: Sandbox, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """SQLite errors produce a report and exit one without a raw traceback."""
        settings = sandbox.config()
        sandbox.paths.state.mkdir(parents=True)
        (sandbox.paths.state / "ownership.sqlite3").write_bytes(b"invalid database")
        assert (
            Application().run(["sync", "--config-file", str(settings.file), "--json"])
            == 1
        )
        assert '"ok": false' in capsys.readouterr().out

    def test_two_processes_converge_under_one_config(self, sandbox: Sandbox) -> None:
        """Actual independent CLI processes serialize overlapping writes."""
        settings = sandbox.config()
        sandbox.put("instructions/rule.md", b"authoritative")
        command = [
            sys.executable,
            "-m",
            "agentsync",
            "sync",
            "--config-file",
            str(settings.file),
            "--json",
        ]
        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(self._run, command) for _ in range(2)]
            results = [future.result(timeout=45) for future in futures]
        assert results == [0, 0]
        assert (
            sandbox.root / "target/instructions/rule/rule.md"
        ).read_bytes() == b"authoritative"
        assert not (sandbox.paths.state / "transaction.json").exists()

    def test_real_watch_event_poll_and_config_reload(self, sandbox: Sandbox) -> None:
        """A real watcher repairs drift/deletions and reloads destination policy."""
        settings = sandbox.config()
        data = Json.object(Json.loads(settings.file.read_text(encoding="utf-8")))
        data["settings"] = {
            "poll": 0.1,
            "verify": 0.2,
            "remote_poll": 0.3,
            "debounce": 0.05,
        }
        settings.file.write_text(Json.dumps(data), encoding="utf-8")
        source = sandbox.put("instructions/rule.md", b"first")
        target = sandbox.root / "target/instructions/rule/rule.md"
        journal = sandbox.paths.state / "transaction.json"
        command = [
            sys.executable,
            "-m",
            "agentsync",
            "watch",
            "--config-file",
            str(settings.file),
        ]
        with subprocess.Popen(  # noqa: S603 - isolated watcher fixture, no shell
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        ) as process:
            try:
                self._eventually(lambda: target.exists() and not journal.exists())
                source.write_bytes(b"second")
                self._eventually(
                    lambda: self._content(target) == b"second" and not journal.exists()
                )
                target.unlink()
                self._eventually(
                    lambda: self._content(target) == b"second" and not journal.exists()
                )
                source.unlink()
                self._eventually(lambda: not target.exists() and not journal.exists())
                sandbox.put("instructions/new.md", b"new")
                destinations = Json.object(data["destinations"])
                Json.object(destinations["target"])["location"] = str(
                    sandbox.root / "second-target"
                )
                # Json.object returns the original validated mapping.
                data["destinations"] = destinations
                settings.file.write_text(Json.dumps(data), encoding="utf-8")
                new_target = sandbox.root / "second-target/instructions/new/new.md"
                self._eventually(lambda: self._content(new_target) == b"new")
            finally:
                process.terminate()
                process.wait(timeout=5)

    @staticmethod
    def _eventually(predicate: Callable[[], bool]) -> None:
        """Bound native event/poll convergence without asserting incidental timing."""
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.02)
        pytest.fail("Watcher did not converge within eight seconds")

    @staticmethod
    def _content(path: Path) -> bytes | None:
        """Read event-driven replacements without introducing a test-side race."""
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None

    @staticmethod
    def _run(command: list[str]) -> int:
        """Capture bounded isolated CLI execution results."""
        return subprocess.run(  # noqa: S603 - explicit fixture argv, no shell
            command, capture_output=True, timeout=40, check=False
        ).returncode
