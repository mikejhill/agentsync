"""SQLite ownership records and persisted distribution reports."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from skillsinc.jsonutil import Json, JsonObject
from skillsinc.models import Digest, Output


class OwnershipStore:
    """Read-only queries do not create state directories or databases."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.file = root / "ownership.sqlite3"

    def records(self) -> dict[str, tuple[str, Output]]:
        """Read all output ownership across configuration files."""
        if not self.file.exists():
            return {}
        with closing(
            sqlite3.connect(f"{self.file.as_uri()}?mode=ro", uri=True)
        ) as connection:
            rows = connection.execute(
                "SELECT owner, path, slot, format, content, target, provenanc"
                "e, mode FROM outputs"
            ).fetchall()
        result = {}
        for owner, path, slot, format_name, content, target, provenance, mode in rows:
            output = Output(
                Path(str(path)),
                bytes(content),
                str(target),
                Json.strings(Json.loads(str(provenance))),
                Json.strings(Json.loads(str(slot))),
                str(format_name),
                int(mode),
            )
            result[output.key] = (str(owner), output)
        return result

    def replace(
        self, owner: str, targets: set[str], outputs: tuple[Output, ...]
    ) -> None:
        """Commit ownership after verified file operations."""
        self.root.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.file)) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS outputs (key TEXT PRIMARY KEY, ow"
                "ner TEXT, path TEXT, slot TEXT, format TEXT, content BLOB, t"
                "arget TEXT, provenance TEXT, mode INTEGER)"
            )
            for target in targets:
                connection.execute(
                    "DELETE FROM outputs WHERE owner=? AND target=?", (owner, target)
                )
            for output in outputs:
                connection.execute(
                    "INSERT OR REPLACE INTO outputs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        output.key,
                        owner,
                        str(output.path),
                        Json.dumps(list(output.slot)),
                        output.format,
                        output.content,
                        output.target,
                        Json.dumps(list(output.provenance)),
                        output.mode,
                    ),
                )

    def report(
        self, value: JsonObject | None = None, *, owner: str | None = None
    ) -> JsonObject:
        """Read or atomically write last distribution status."""
        file = self.root / (
            "status-" + Digest.of(owner.encode()) + ".json"
            if owner is not None
            else "status.json"
        )
        if value is None:
            return (
                Json.object(Json.loads(file.read_text(encoding="utf-8")))
                if file.exists()
                else {"version": 1, "state": "never-run"}
            )
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = file.with_suffix(".tmp")
        temporary.write_text(Json.dumps(value), encoding="utf-8")
        temporary.replace(file)
        config = value.get("config")
        if owner is None and isinstance(config, str):
            self.report(value, owner=config)
        return value

    def watcher(self, value: JsonObject | None = None) -> JsonObject:
        """Persist or inspect background heartbeat without destination writes."""
        file = self.root / "watcher.json"
        if value is None:
            return (
                Json.object(Json.loads(file.read_text(encoding="utf-8")))
                if file.exists()
                else {"state": "not-running"}
            )
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = file.with_suffix(".tmp")
        temporary.write_text(Json.dumps(value), encoding="utf-8")
        temporary.replace(file)
        return value
