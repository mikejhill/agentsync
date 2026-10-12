"""XDG roots and filesystem containment checks."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from agentsync.exceptions import ConfigurationError


@dataclass(frozen=True, slots=True)
class XdgPaths:
    """Application-owned storage roots."""

    config: Path
    data: Path
    state: Path
    cache: Path

    @classmethod
    def discover(cls) -> XdgPaths:
        """Honor absolute XDG overrides on every operating system."""
        roots = []
        variables = (
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_STATE_HOME",
            "XDG_CACHE_HOME",
        )
        defaults = (".config", ".local/share", ".local/state", ".cache")
        for variable, default in zip(variables, defaults, strict=True):
            raw = os.environ.get(variable)
            root = Path(raw) if bool(raw) else Path.home() / default
            if not root.is_absolute():
                raise ConfigurationError(f"{variable} must be absolute")
            roots.append(root / "agentsync")
        return cls(*roots)


class SafePath:
    """Configured path resolution and portable package names."""

    FIRST_PRINTABLE = 32

    @staticmethod
    def configured(raw: str, base: Path) -> Path:
        """Resolve tilde and configuration-relative paths."""
        path = Path(raw).expanduser()
        return (path if path.is_absolute() else base / path).absolute()

    @staticmethod
    def relative(raw: str) -> str:
        """Reject traversal and Windows aliases."""
        normalized = raw.replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            not path.parts
            or path.is_absolute()
            or any(part in (".", "..", "") for part in normalized.split("/"))
        ):
            raise ConfigurationError(f"Unsafe package path: {raw}")
        reserved = {
            "con",
            "prn",
            "aux",
            "nul",
            *(f"com{i}" for i in range(1, 10)),
            *(f"lpt{i}" for i in range(1, 10)),
        }
        if any(
            ":" in part
            or any(character in part for character in '<>"|?*')
            or any(ord(character) < SafePath.FIRST_PRINTABLE for character in part)
            or part.endswith((".", " "))
            or part.split(".")[0].casefold() in reserved
            for part in path.parts
        ):
            raise ConfigurationError(f"Non-portable package path: {raw}")
        return path.as_posix()

    @classmethod
    def child(cls, root: Path, relative: str) -> Path:
        """Resolve a contained path without writable symlink ancestors."""
        result = root / cls.relative(relative)
        if not result.resolve().is_relative_to(root.resolve()):
            raise ConfigurationError(f"Path escapes root: {result}")
        current = result
        while current != root.parent:
            if current.is_symlink() or current.is_junction():
                raise ConfigurationError(f"Symlink destination: {current}")
            current = current.parent
        return result
