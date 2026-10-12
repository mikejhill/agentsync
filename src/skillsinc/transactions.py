"""Preconditioned file commits with durable rollback and crash recovery."""

from __future__ import annotations

import base64
import os
import sqlite3
import tempfile
from pathlib import Path

from skillsinc.exceptions import ConflictError, TransactionError
from skillsinc.jsonutil import Json, JsonObject, JsonValue
from skillsinc.models import Operation, Output
from skillsinc.state import OwnershipStore


class OutputCodec:
    """Versioned journal serialization for binary outputs."""

    @staticmethod
    def encode(output: Output) -> JsonObject:
        """Encode ownership without losing binary content."""
        return {
            "path": str(output.path),
            "content": base64.b64encode(output.content).decode(),
            "target": output.target,
            "provenance": list(output.provenance),
            "slot": list(output.slot),
            "format": output.format,
            "mode": output.mode,
        }

    @staticmethod
    def decode(record: JsonObject) -> Output:
        """Decode a persisted desired output."""
        mode = record.get("mode", 0o644)
        if not isinstance(mode, int):
            raise TransactionError("Invalid journal mode")
        return Output(
            Path(Json.string(record.get("path"))),
            base64.b64decode(Json.string(record.get("content")), validate=True),
            Json.string(record.get("target")),
            Json.strings(record.get("provenance")),
            Json.strings(record.get("slot")),
            Json.string(record.get("format")),
            mode,
        )


class TransactionManager:
    """Recoverable commit groups, with individual atomic file replacements."""

    def __init__(self, store: OwnershipStore) -> None:
        self.store = store
        self.journal = store.root / "transaction.json"

    def apply(
        self,
        owner: str,
        targets: set[str],
        operations: tuple[Operation, ...],
        outputs: tuple[Output, ...],
    ) -> None:
        """Journal, validate preconditions, apply, verify, and commit ownership."""
        records = self.store.records()
        desired = {output.key: output for output in outputs}
        current = {
            key: output
            for key, (record_owner, output) in records.items()
            if record_owner == owner and output.target in targets
        }
        if not operations and desired == current:
            return
        self.store.root.mkdir(parents=True, exist_ok=True)
        previous = tuple(
            output
            for record_owner, output in self.store.records().values()
            if record_owner == owner and output.target in targets
        )
        data = Json.record(
            {
                "version": 1,
                "owner": owner,
                "targets": sorted(targets),
                "previous": [OutputCodec.encode(output) for output in previous],
                "outputs": [OutputCodec.encode(output) for output in outputs],
                "operations": [
                    self._encode_operation(operation) for operation in operations
                ],
            }
        )
        for operation in operations:
            if self.read(operation.path) != operation.before:
                raise ConflictError(
                    f"Destination changed after planning: {operation.path}"
                )
        self._write_journal(data)
        try:
            self._commit_files(operations)
            self.store.replace(owner, targets, outputs)
            self.journal.unlink()
        except (OSError, sqlite3.Error, ConflictError, TransactionError) as error:
            self.recover()
            raise TransactionError(
                "Distribution rolled back after commit failure"
            ) from error

    def _commit_files(self, operations: tuple[Operation, ...]) -> None:
        """Check each precondition immediately before replacement."""
        for operation in operations:
            if self.read(operation.path) != operation.before:
                raise ConflictError(
                    f"Destination changed during commit: {operation.path}"
                )
            self.write(operation.path, operation.after, operation.mode)
            if self.read(operation.path) != operation.after:
                raise TransactionError(f"Verification failed: {operation.path}")

    def recover(self) -> None:
        """Roll back an interrupted group before any new distribution."""
        if not self.journal.exists():
            return
        data = Json.object(Json.loads(self.journal.read_text(encoding="utf-8")))
        if data.get("version") != 1:
            raise TransactionError("Unsupported transaction journal version")
        operations = tuple(
            self._decode_operation(Json.object(raw))
            for raw in Json.array(data.get("operations"))
        )
        try:
            for operation in reversed(operations):
                self._rollback(operation)
            previous = tuple(
                OutputCodec.decode(Json.object(raw))
                for raw in Json.array(data.get("previous"))
            )
            self.store.replace(
                Json.string(data.get("owner")),
                set(Json.strings(data.get("targets"))),
                previous,
            )
            self.journal.unlink()
        except OSError as error:
            raise TransactionError(
                "Recovery failed; journal retained for next run"
            ) from error

    def _rollback(self, operation: Operation) -> None:
        """Restore only changed files and preserve preexisting permission bits."""
        current = self.read(operation.path)
        if current not in (operation.before, operation.after):
            raise TransactionError(
                f"Recovery blocked by external edit: {operation.path}"
            )
        changed_mode = (
            current is not None
            and os.name != "nt"
            and operation.path.stat().st_mode & 0o777 != operation.before_mode
        )
        if current != operation.before or changed_mode:
            self.write(operation.path, operation.before, operation.before_mode)

    def _write_journal(self, data: JsonObject) -> None:
        """Flush rollback data before touching destination files."""
        temporary = self.journal.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(Json.dumps(data))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.journal)

    @staticmethod
    def read(path: Path) -> bytes | None:
        """Read an optional regular destination file."""
        if path.is_symlink():
            raise ConflictError(f"Destination is a symlink: {path}")
        TransactionManager._validate_parents(path)
        return path.read_bytes() if path.exists() else None

    @staticmethod
    def write(path: Path, content: bytes | None, mode: int) -> None:
        """Replace from a same-filesystem staged file."""
        TransactionManager._validate_parents(path)
        if content is None:
            path.unlink(missing_ok=True)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".skillsinc-", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(mode)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _validate_parents(path: Path) -> None:
        """Reject links introduced between rendering and commit."""
        if any(
            parent.is_symlink() or parent.is_junction()
            for parent in (path, *path.parents)
        ):
            raise ConflictError(f"Destination contains a symlink: {path}")

    @staticmethod
    def _encode_operation(operation: Operation) -> JsonObject:
        """Store rollback and proposed content."""
        return {
            "path": str(operation.path),
            "before": base64.b64encode(operation.before).decode()
            if operation.before is not None
            else None,
            "after": base64.b64encode(operation.after).decode()
            if operation.after is not None
            else None,
            "mode": operation.mode,
            "before_mode": operation.before_mode,
        }

    @staticmethod
    def _decode_operation(value: JsonObject) -> Operation:
        """Restore a binary-safe operation."""
        before = value.get("before")
        after = value.get("after")
        mode = value.get("mode", 0o644)
        before_mode = value.get("before_mode", 0o644)
        if not isinstance(mode, int) or not isinstance(before_mode, int):
            raise TransactionError("Invalid operation mode")
        return Operation(
            Path(Json.string(value.get("path"))),
            TransactionManager._decode_bytes(before),
            TransactionManager._decode_bytes(after),
            mode,
            before_mode,
        )

    @staticmethod
    def _decode_bytes(value: JsonValue) -> bytes | None:
        """Decode optional journal content."""
        return (
            base64.b64decode(Json.string(value), validate=True)
            if value is not None
            else None
        )
