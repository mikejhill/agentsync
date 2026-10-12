"""Fault injection, crash recovery, and authoritative snapshot tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import override

import pytest
from tests.conftest import Sandbox

from skillsinc.config import Source
from skillsinc.exceptions import ConflictError, SourceError, TransactionError
from skillsinc.jsonutil import Json
from skillsinc.models import Operation, Output
from skillsinc.sources import GitSource, LocalSource
from skillsinc.state import OwnershipStore
from skillsinc.transactions import OutputCodec, TransactionManager


class FailingTransaction(TransactionManager):
    """Fail after one file replacement to exercise rollback."""

    @override
    def _commit_files(self, operations: tuple[Operation, ...]) -> None:
        """Inject an I/O failure after a partial commit."""
        first = operations[0]
        self.write(first.path, first.after, first.mode)
        raise OSError("injected write failure")


class TestTransactions:
    """Preconditions and rollback cover file and ownership state."""

    def test_verified_commit_and_codec(self, sandbox: Sandbox) -> None:
        """Verified files and binary ownership records commit together."""
        path = sandbox.root / "target/file.bin"
        output = Output(path, b"\x00binary", "target", ("source:test",))
        store = OwnershipStore(sandbox.paths.state)
        manager = TransactionManager(store)
        manager.apply(
            "owner", {"target"}, (Operation(path, None, output.content),), (output,)
        )
        assert path.read_bytes() == output.content
        assert OutputCodec.decode(OutputCodec.encode(output)) == output
        assert store.records()[output.key] == ("owner", output)
        assert not manager.journal.exists()
        manager.recover()

    def test_partial_failure_restores_original_state(self, sandbox: Sandbox) -> None:
        """A failed group restores original files and ownership."""
        first = sandbox.root / "first"
        second = sandbox.root / "second"
        first.write_bytes(b"original")
        store = OwnershipStore(sandbox.paths.state)
        with pytest.raises(TransactionError, match="rolled back"):
            FailingTransaction(store).apply(
                "owner",
                {"target"},
                (
                    Operation(first, b"original", b"new"),
                    Operation(second, None, b"created"),
                ),
                (),
            )
        assert first.read_bytes() == b"original"
        assert not second.exists()
        assert store.records() == {}

    def test_precondition_failure_writes_nothing(self, sandbox: Sandbox) -> None:
        """External edits after planning fail before destination replacement."""
        path = sandbox.root / "target"
        path.write_bytes(b"external")
        manager = TransactionManager(OwnershipStore(sandbox.paths.state))
        with pytest.raises(ConflictError, match="changed"):
            manager.apply("owner", {"target"}, (Operation(path, b"old", b"new"),), ())
        assert path.read_bytes() == b"external"
        assert not manager.journal.exists()

    def test_interrupted_journal_recovery(self, sandbox: Sandbox) -> None:
        """A persisted precommit journal restores an interrupted file."""
        path = sandbox.root / "target"
        path.write_bytes(b"new")
        store = OwnershipStore(sandbox.paths.state)
        store.root.mkdir(parents=True)
        operation = {"path": str(path), "before": "b2xk", "after": "bmV3", "mode": 420}
        journal = store.root / "transaction.json"
        journal.write_text(
            Json.dumps(
                {
                    "version": 1,
                    "owner": "owner",
                    "targets": ["target"],
                    "previous": [],
                    "outputs": [],
                    "operations": [operation],
                }
            ),
            encoding="utf-8",
        )
        TransactionManager(store).recover()
        assert path.read_bytes() == b"old"
        assert not journal.exists()

    def test_external_edit_blocks_recovery(self, sandbox: Sandbox) -> None:
        """Recovery never overwrites edits outside its journal preconditions."""
        path = sandbox.root / "target"
        path.write_bytes(b"external")
        store = OwnershipStore(sandbox.paths.state)
        store.root.mkdir(parents=True)
        journal = store.root / "transaction.json"
        journal.write_text(
            Json.dumps(
                {
                    "version": 1,
                    "owner": "owner",
                    "targets": ["target"],
                    "previous": [],
                    "outputs": [],
                    "operations": [
                        {
                            "path": str(path),
                            "before": "b2xk",
                            "after": "bmV3",
                            "mode": 420,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(TransactionError, match="external edit"):
            TransactionManager(store).recover()
        assert journal.exists()

    def test_invalid_journal_version(self, sandbox: Sandbox) -> None:
        """Unknown recovery formats cannot be applied."""
        store = OwnershipStore(sandbox.paths.state)
        store.root.mkdir(parents=True)
        (store.root / "transaction.json").write_text('{"version":2}', encoding="utf-8")
        with pytest.raises(TransactionError, match="version"):
            TransactionManager(store).recover()

    def test_invalid_codec_mode(self, sandbox: Sandbox) -> None:
        """Journal types are validated before reading binary payloads."""
        record = OutputCodec.encode(Output(sandbox.root / "x", b"", "x", ()))
        record["mode"] = "bad"
        with pytest.raises(TransactionError, match="mode"):
            OutputCodec.decode(record)


class TestLocalSource:
    """Local snapshots fail closed on missing or unreadable input."""

    def test_stable_snapshot_includes_binary_and_mode(self, sandbox: Sandbox) -> None:
        """The same tree has a deterministic content revision."""
        sandbox.put("instructions/rule.md", b"\x00binary")
        source = LocalSource(sandbox.root / "source")
        first = source.snapshot()
        assert first.revision == source.snapshot().revision
        assert first.files[0].content == b"\x00binary"

    def test_missing_root(self, sandbox: Sandbox) -> None:
        """A missing root is unavailable rather than authoritative emptiness."""
        with pytest.raises(SourceError, match="unavailable"):
            LocalSource(sandbox.root / "missing").snapshot()

    def test_unreadable_file(
        self, sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An individual read failure invalidates the complete snapshot."""
        sandbox.put("instructions/rule.md")
        monkeypatch.setattr(Path, "read_bytes", self._denied)
        with pytest.raises(SourceError, match="Incomplete"):
            LocalSource(sandbox.root / "source").snapshot()

    @staticmethod
    def _denied(path: Path) -> bytes:
        """Simulate a source permission failure."""
        raise PermissionError(str(path))


class TestGitSource:
    """Real local Git repositories exercise fetch and archive boundaries."""

    def test_local_repository_polling_and_failed_fetch(self, sandbox: Sandbox) -> None:
        """Public-repo mechanics work without network or checkout scripts."""
        repository = sandbox.root / "repository"
        repository.mkdir()
        self.git(repository, "init")
        self.git(repository, "config", "user.name", "Test")
        self.git(repository, "config", "user.email", "test@example.invalid")
        (repository / "instructions").mkdir()
        file = repository / "instructions/rule.md"
        file.write_bytes(b"first")
        self.git(repository, "add", ".")
        self.git(repository, "commit", "-m", "first")
        source = Source("remote", str(repository), "git")
        provider = GitSource(source, sandbox.paths.cache)
        first = provider.snapshot()
        file.write_bytes(b"second")
        self.git(repository, "add", ".")
        self.git(repository, "commit", "-m", "second")
        second = provider.snapshot()
        assert first.revision != second.revision
        assert second.files[0].content == b"second"
        assert (
            GitSource(source, sandbox.paths.cache, fetch=False).snapshot().revision
            == second.revision
        )
        bad = GitSource(
            Source("bad", str(repository / "missing"), "git"), sandbox.paths.cache
        )
        with pytest.raises(SourceError, match="Git"):
            bad.snapshot()

    @staticmethod
    def git(root: Path, *arguments: str) -> None:
        """Run fixture-only Git commands in an isolated repository."""
        subprocess.run(  # noqa: S603 - isolated Git fixtures, no shell
            ["git", "-C", str(root), *arguments],  # noqa: S607 - fixture executable
            check=True,
            capture_output=True,
        )
