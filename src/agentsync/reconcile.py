"""Pure desired-state reconciliation against bounded ownership."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from agentsync.documents import Documents
from agentsync.exceptions import ConflictError
from agentsync.models import Operation, Output
from agentsync.transactions import TransactionManager


@dataclass(frozen=True, slots=True)
class FileState:
    """One physical file's ownership and desired slots."""

    owner: str
    desired: dict[str, Output]
    previous: dict[str, Output]
    records: dict[str, tuple[str, Output]]


class Reconciler:
    """Plan whole-file operations without changing files or state."""

    def plan(
        self,
        owner: str,
        targets: set[str],
        outputs: tuple[Output, ...],
        records: dict[str, tuple[str, Output]],
        *,
        adopt: bool = False,
    ) -> tuple[Operation, ...]:
        """Merge managed entries and remove confirmed stale outputs."""
        desired = {output.key: output for output in outputs}
        previous = {
            key: output
            for key, (record_owner, output) in records.items()
            if record_owner == owner and output.target in targets
        }
        desired_by_path: dict[Path, dict[str, Output]] = {}
        previous_by_path: dict[Path, dict[str, Output]] = {}
        records_by_path: dict[Path, dict[str, tuple[str, Output]]] = {}
        for key, output in desired.items():
            desired_by_path.setdefault(output.canonical, {})[key] = output
        for key, output in previous.items():
            previous_by_path.setdefault(output.canonical, {})[key] = output
        for key, record in records.items():
            records_by_path.setdefault(record[1].canonical, {})[key] = record
        paths = sorted(desired_by_path.keys() | previous_by_path.keys())
        operations = []
        for path in paths:
            before = TransactionManager.read(path)
            context = FileState(
                owner,
                desired_by_path.get(path, {}),
                previous_by_path.get(path, {}),
                records_by_path.get(path, {}),
            )
            after = self._reconcile_file(before, context, adopt=adopt)
            mode = next((output.mode for output in context.desired.values()), 0o644)
            before_mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
            if before is not None and any(
                output.slot for output in context.desired.values()
            ):
                mode = before_mode
            if before != after or (
                after is not None
                and os.name != "nt"
                and path.exists()
                and path.stat().st_mode & 0o777 != mode
            ):
                operations.append(Operation(path, before, after, mode, before_mode))
        return tuple(operations)

    def _reconcile_file(
        self,
        before: bytes | None,
        context: FileState,
        *,
        adopt: bool,
    ) -> bytes | None:
        """Compose all owned slots of one physical document."""
        after = before
        for key, output in context.previous.items():
            if key not in context.desired:
                after = (
                    Documents.edit(after, output.format, output.slot, None)
                    if output.slot
                    else None
                )
        for output in context.desired.values():
            self._check(output, context.owner, context.records, before, adopt=adopt)
            after = (
                Documents.edit(after, output.format, output.slot, output.content)
                if output.slot
                else output.content
            )
        return after

    @staticmethod
    def _check(
        output: Output,
        owner: str,
        records: dict[str, tuple[str, Output]],
        before: bytes | None,
        *,
        adopt: bool,
    ) -> None:
        """Reject unmanaged collisions and another configuration's ownership."""
        for key, (record_owner, record) in records.items():
            if record.canonical != output.canonical:
                continue
            overlapping = (
                not record.slot
                or not output.slot
                or record.slot[: len(output.slot)] == output.slot
                or output.slot[: len(record.slot)] == record.slot
            )
            if overlapping and (record_owner != owner or key != output.key):
                raise ConflictError(f"Overlapping ownership: {output.path}")
        record = records.get(output.key)
        existing = (
            Documents.get(before, output.format, output.slot) if output.slot else before
        )
        if record is None and existing is not None and not adopt:
            raise ConflictError(
                f"Unmanaged collision: {output.path} {'/'.join(output.slot)}; "
                "use adopt or reroute"
            )
