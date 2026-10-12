"""Typed immutable values and extension protocols."""

from __future__ import annotations

import hashlib
from abc import abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from agentsync.jsonutil import Json, JsonObject


@dataclass(frozen=True, slots=True)
class PackageFile:
    """Contained package content and permission bits."""

    path: str
    content: bytes
    mode: int = 0o644


@dataclass(frozen=True, slots=True)
class Customization:
    """Semantic customization with preserved native metadata."""

    name: str
    kind: str
    files: tuple[PackageFile, ...]
    metadata: JsonObject
    style: str = "portable"
    source: str = ""
    origins: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Complete source revision."""

    root: Path
    revision: str
    files: tuple[PackageFile, ...]


@dataclass(frozen=True, slots=True)
class Output:
    """Desired complete file or structured-document slot."""

    path: Path
    content: bytes
    target: str
    provenance: tuple[str, ...]
    slot: tuple[str, ...] = ()
    format: str = "file"
    mode: int = 0o644
    canonical: Path = field(init=False, repr=False, compare=False)
    _key: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Resolve physical identity once per immutable proposed output."""
        canonical = self.path.resolve()
        object.__setattr__(self, "canonical", canonical)
        object.__setattr__(
            self, "_key", str(canonical) + "#" + Json.dumps(list(self.slot)).strip()
        )

    @property
    def key(self) -> str:
        """Return a physical ownership key."""
        return self._key


@dataclass(frozen=True, slots=True)
class Operation:
    """Preconditioned physical-file change."""

    path: Path
    before: bytes | None
    after: bytes | None
    mode: int = 0o644
    before_mode: int = 0o644


class SourceProvider(Protocol):
    """Complete snapshot provider boundary."""

    @abstractmethod
    def snapshot(self) -> Snapshot:
        """Return a complete revision."""
        raise NotImplementedError


class CustomizationReader(Protocol):
    """Source interpretation boundary."""

    @abstractmethod
    def read(
        self, snapshot: Snapshot, source: str, style: str
    ) -> tuple[Customization, ...]:
        """Interpret packages without losing metadata."""
        raise NotImplementedError


class Transformation(Protocol):
    """Zero-to-many ordered transformation boundary."""

    @abstractmethod
    def apply(
        self, items: tuple[Customization, ...], options: JsonObject
    ) -> tuple[Customization, ...]:
        """Return proposed customizations without destination writes."""
        raise NotImplementedError


class DestinationRenderer(Protocol):
    """Harness rendering boundary."""

    @abstractmethod
    def render(self, item: Customization) -> tuple[Output, ...]:
        """Return proposed outputs."""
        raise NotImplementedError


class Digest:
    """Shared content hashing."""

    @staticmethod
    def of(content: bytes) -> str:
        """Return SHA-256."""
        return hashlib.sha256(content).hexdigest()
