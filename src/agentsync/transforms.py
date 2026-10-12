"""Ordered built-in and third-party transformation execution."""

from __future__ import annotations

import fnmatch
import importlib.metadata
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import cast

from agentsync.config import Step
from agentsync.exceptions import ConfigurationError
from agentsync.jsonutil import Json, JsonObject, JsonValue
from agentsync.models import Customization, PackageFile, Transformation
from agentsync.paths import SafePath
from agentsync.readers import Frontmatter
from agentsync.sources import LocalSource


class Selection:
    """Shared customization selectors."""

    @staticmethod
    def matches(item: Customization, patterns: tuple[str, ...]) -> bool:
        """Match name or kind/name without filesystem-dependent casing."""
        return any(
            fnmatch.fnmatchcase(item.name, pattern)
            or fnmatch.fnmatchcase(f"{item.kind}/{item.name}", pattern)
            for pattern in patterns
        )


class BuiltinTransform:
    """Small composable collection transformations."""

    def __init__(self, name: str) -> None:
        self.name = name

    def apply(
        self, items: tuple[Customization, ...], options: JsonObject
    ) -> tuple[Customization, ...]:
        """Apply one explicitly selected operation."""
        handlers = {
            "select": self._select,
            "exclude": self._exclude,
            "rename": self._rename,
            "prefix": self._prefix,
            "replace": self._replace,
            "metadata": self._metadata,
            "path-map": self._paths,
            "split": self._split,
            "compose": self._compose,
            "format": self._format,
        }
        return handlers[self.name](items, options)

    @staticmethod
    def _select(
        items: tuple[Customization, ...], options: JsonObject
    ) -> tuple[Customization, ...]:
        """Keep matching items."""
        patterns = Json.strings(options.get("patterns", ["*"]))
        return tuple(item for item in items if Selection.matches(item, patterns))

    @staticmethod
    def _exclude(
        items: tuple[Customization, ...], options: JsonObject
    ) -> tuple[Customization, ...]:
        """Drop matching items."""
        patterns = Json.strings(options.get("patterns", []))
        return tuple(item for item in items if not Selection.matches(item, patterns))

    @staticmethod
    def _rename(
        items: tuple[Customization, ...], options: JsonObject
    ) -> tuple[Customization, ...]:
        """Rename by explicit mapping."""
        mapping = Json.object(options.get("names", {}))
        return tuple(
            replace(
                item,
                name=SafePath.relative(Json.string(mapping.get(item.name, item.name))),
            )
            for item in items
        )

    @staticmethod
    def _prefix(
        items: tuple[Customization, ...], options: JsonObject
    ) -> tuple[Customization, ...]:
        """Strip then add a name prefix."""
        remove = Json.string(options.get("remove", ""))
        add = Json.string(options.get("add", ""))
        return tuple(
            replace(item, name=SafePath.relative(add + item.name.removeprefix(remove)))
            for item in items
        )

    @staticmethod
    def _replace(
        items: tuple[Customization, ...], options: JsonObject
    ) -> tuple[Customization, ...]:
        """Replace literal text in selected package files."""
        old = Json.string(options.get("old"))
        new = Json.string(options.get("new"))
        pattern = Json.string(options.get("files", "*.md"))
        return tuple(
            replace(
                item,
                files=tuple(
                    replace(
                        file, content=file.content.replace(old.encode(), new.encode())
                    )
                    if fnmatch.fnmatchcase(file.path, pattern)
                    else file
                    for file in item.files
                ),
            )
            for item in items
        )

    @staticmethod
    def _metadata(
        items: tuple[Customization, ...], options: JsonObject
    ) -> tuple[Customization, ...]:
        """Update preserved metadata."""
        updates = Json.object(options.get("set", {}))
        remove = Json.strings(options.get("remove", []))
        return tuple(
            replace(
                item,
                metadata={
                    key: value
                    for key, value in (item.metadata | updates).items()
                    if key not in remove
                },
            )
            for item in items
        )

    @staticmethod
    def _paths(
        items: tuple[Customization, ...], options: JsonObject
    ) -> tuple[Customization, ...]:
        """Map supporting-file paths explicitly."""
        mapping = Json.object(options.get("paths", {}))
        return tuple(
            replace(
                item,
                files=tuple(
                    replace(
                        file,
                        path=SafePath.relative(
                            Json.string(mapping.get(file.path, file.path))
                        ),
                    )
                    for file in item.files
                ),
            )
            for item in items
        )

    @staticmethod
    def _split(
        items: tuple[Customization, ...], options: JsonObject
    ) -> tuple[Customization, ...]:
        """Duplicate collections under explicitly configured names."""
        names = Json.strings(options.get("names"))
        return tuple(
            replace(item, name=SafePath.relative(name))
            for item in items
            for name in names
        )

    @staticmethod
    def _compose(
        items: tuple[Customization, ...], options: JsonObject
    ) -> tuple[Customization, ...]:
        """Compose Markdown bodies into one customization."""
        if not items:
            return ()
        body = "\n".join(Frontmatter.read(item.files[0].content)[1] for item in items)
        name = SafePath.relative(Json.string(options.get("name")))
        return (
            Customization(
                name,
                Json.string(options.get("kind", "instructions")),
                (PackageFile(name + ".md", body.encode()),),
                {},
                source=",".join(item.source for item in items),
                origins=tuple(origin for item in items for origin in item.origins),
            ),
        )

    @staticmethod
    def _format(
        items: tuple[Customization, ...], options: JsonObject
    ) -> tuple[Customization, ...]:
        """Explicitly change declared kind/style after user conversion steps."""
        return tuple(
            replace(
                item,
                kind=Json.string(options.get("kind", item.kind)),
                style=Json.string(options.get("style", item.style)),
            )
            for item in items
        )


class ExecutableTransform:
    """Versioned staged-package protocol for trusted external programs."""

    MAX_OUTPUT = 4 * 1024 * 1024

    def apply(
        self, items: tuple[Customization, ...], options: JsonObject
    ) -> tuple[Customization, ...]:
        """Execute a configured argv with bounded protocol output."""
        argv = Json.strings(options.get("argv"))
        if not argv:
            raise ConfigurationError("Executable transformation needs argv")
        with tempfile.TemporaryDirectory(prefix="agentsync-transform-") as directory:
            root = Path(directory)
            request = self._stage(items, root)
            content = self._execute(
                argv, request, Json.number(options.get("timeout", 30))
            )
            response = Json.object(Json.loads(content.decode("utf-8")))
            if response.get("version") != 1:
                raise ConfigurationError("Unsupported transformation protocol version")
            return self._read(response, root)

    @classmethod
    def _execute(
        cls, argv: tuple[str, ...], request: JsonObject, timeout: float
    ) -> bytes:
        """Stop a process immediately when protocol output exceeds its bound."""
        try:
            with (
                subprocess.Popen(  # noqa: S603 - trusted argv, no shell
                    argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                ) as process,
                ThreadPoolExecutor(max_workers=2) as workers,
            ):
                if process.stdin is None or process.stdout is None:
                    raise ConfigurationError("Plugin pipes unavailable")
                reader = workers.submit(process.stdout.read, cls.MAX_OUTPUT + 1)
                writer = workers.submit(
                    cls._send, process, Json.dumps(request).encode()
                )
                try:
                    content = reader.result(timeout=timeout)
                    if len(content) > cls.MAX_OUTPUT:
                        raise ConfigurationError(
                            "Executable exceeded protocol output limit"
                        )
                    process.wait(timeout=timeout)
                    writer.result(timeout=timeout)
                    if process.returncode:
                        raise ConfigurationError("Executable transformation failed")
                    return content
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
        except (OSError, TimeoutError, subprocess.SubprocessError) as error:
            raise ConfigurationError(
                "Executable transformation failed or timed out"
            ) from error

    @staticmethod
    def _send(process: subprocess.Popen[bytes], payload: bytes) -> None:
        """Write protocol input concurrently with bounded output collection."""
        if process.stdin is None:
            raise ConfigurationError("Plugin input pipe unavailable")
        process.stdin.write(payload)
        process.stdin.close()

    @staticmethod
    def _stage(items: tuple[Customization, ...], root: Path) -> JsonObject:
        """Stage input packages and send their absolute locations."""
        records: list[JsonValue] = []
        for index, item in enumerate(items):
            package = root / str(index)
            for file in item.files:
                path = SafePath.child(package, file.path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(file.content)
                path.chmod(file.mode)
            records.append(
                {
                    "name": item.name,
                    "kind": item.kind,
                    "style": item.style,
                    "source": item.source,
                    "origins": list(item.origins),
                    "metadata": item.metadata,
                    "package": str(package),
                }
            )
        return {"version": 1, "workspace": str(root), "customizations": records}

    @staticmethod
    def _read(response: JsonObject, root: Path) -> tuple[Customization, ...]:
        """Validate outputs remain within staging."""
        items = []
        for raw in Json.array(response.get("customizations")):
            record = Json.object(raw)
            package = Path(Json.string(record.get("package")))
            if not package.resolve().is_relative_to(root.resolve()):
                raise ConfigurationError("Plugin package escapes staging")
            files = LocalSource(package).snapshot().files
            items.append(
                Customization(
                    SafePath.relative(Json.string(record.get("name"))),
                    Json.string(record.get("kind")),
                    files,
                    Json.object(record.get("metadata", {})),
                    Json.string(record.get("style", "portable")),
                    Json.string(record.get("source", "plugin")),
                    Json.strings(record.get("origins", [])),
                )
            )
        return tuple(items)


class TransformRegistry:
    """Resolve installed entry points and run explicit ordered pipelines."""

    BUILTINS = (
        "select",
        "exclude",
        "rename",
        "prefix",
        "replace",
        "metadata",
        "path-map",
        "split",
        "compose",
        "format",
    )

    def resolve(self, name: str) -> Transformation:
        """Load a named trusted transformation."""
        if name in self.BUILTINS:
            return BuiltinTransform(name)
        if name == "executable":
            return ExecutableTransform()
        entries = importlib.metadata.entry_points(
            group="agentsync.transformations", name=name
        )
        if len(entries) != 1:
            raise ConfigurationError(f"Unknown or ambiguous transformation {name}")
        instance: object = entries[0].load()()
        if not callable(getattr(instance, "apply", None)):
            raise ConfigurationError(f"Invalid transformation entry point {name}")
        # Trusted plugins implement the structural transformation protocol.
        return cast(Transformation, instance)

    def apply(
        self, items: tuple[Customization, ...], steps: tuple[Step, ...]
    ) -> tuple[Customization, ...]:
        """Apply collection steps in the exact configured order."""
        for step in steps:
            items = self.resolve(step.use).apply(items, step.options)
        return items
