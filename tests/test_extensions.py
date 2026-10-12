"""Real entry-point loading with injected installed-plugin metadata."""

from __future__ import annotations

import importlib.metadata
from dataclasses import replace
from pathlib import Path

import pytest
from tests.conftest import Sandbox

from skillsinc.config import Destination, Source, Step
from skillsinc.engine import Engine
from skillsinc.exceptions import ConfigurationError
from skillsinc.jsonutil import Json, JsonObject
from skillsinc.models import Customization, Output, Snapshot
from skillsinc.readers import PackageReader
from skillsinc.sources import LocalSource
from skillsinc.transforms import TransformRegistry


class FixtureProvider:
    """Installed source provider obtains a complete local snapshot."""

    def __init__(self, source: Source, cache: Path) -> None:
        self.source = source
        self.cache = cache

    def snapshot(self) -> Snapshot:
        """Use the provider-specific configured root."""
        return LocalSource(Path(self.source.location)).snapshot()


class FixtureReader(PackageReader):
    """Installed reader uses the default semantic representation."""


class FixtureTransformation:
    """Installed transformation carries native metadata through a rename."""

    def apply(
        self, items: tuple[Customization, ...], options: JsonObject
    ) -> tuple[Customization, ...]:
        """Honor namespaced extension options."""
        return tuple(
            replace(item, name=Json.string(options.get("plugin.name")))
            for item in items
        )


class FixtureRenderer:
    """Installed renderer proposes files while the core retains write ownership."""

    def __init__(self, destination: Destination) -> None:
        self.destination = destination

    def render(self, item: Customization) -> tuple[Output, ...]:
        """Return an absolute proposed file and source provenance."""
        return (
            Output(
                self.destination.location / (item.name + ".txt"),
                item.files[0].content,
                self.destination.name,
                (item.source,),
            ),
        )


class TestInstalledExtensions:
    """All four extension seams compose through ordinary distribution."""

    @staticmethod
    def entries(*, group: str, name: str) -> tuple[importlib.metadata.EntryPoint, ...]:
        """Return real entry points pointing at independently defined test plugins."""
        classes = {
            "skillsinc.sources": "FixtureProvider",
            "skillsinc.readers": "FixtureReader",
            "skillsinc.transformations": "FixtureTransformation",
            "skillsinc.renderers": "FixtureRenderer",
        }
        return (
            importlib.metadata.EntryPoint(
                name, "tests.test_extensions:" + classes[group], group
            ),
        )

    def test_end_to_end_plugin_composition(
        self, sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All extension seams compose without reconciler changes."""
        monkeypatch.setattr(importlib.metadata, "entry_points", self.entries)
        settings = sandbox.config()
        source = replace(settings.sources[0], provider="fixture", reader="fixture")
        destination = replace(settings.destinations[0], options={"renderer": "fixture"})
        route = replace(
            settings.routes[0], steps=(Step("fixture", {"plugin.name": "converted"}),)
        )
        sandbox.put("instructions/rule.md", b"content")
        report = Engine(sandbox.paths).run(
            replace(
                settings,
                sources=(source,),
                destinations=(destination,),
                routes=(route,),
            ),
            apply=True,
        )
        assert report["ok"] is True
        assert (sandbox.root / "target/converted.txt").read_bytes() == b"content"
        assert not (sandbox.paths.cache / "conversions").exists()

    def test_invalid_transform_implementation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Installed entries must implement the typed transformation boundary."""
        monkeypatch.setattr(importlib.metadata, "entry_points", self.invalid_entry)
        with pytest.raises(ConfigurationError, match="Invalid"):
            TransformRegistry().resolve("invalid")

    @staticmethod
    def invalid_entry(
        *, group: str, name: str
    ) -> tuple[importlib.metadata.EntryPoint, ...]:
        """A loadable class without apply is an invalid transformation."""
        return (
            importlib.metadata.EntryPoint(
                name, "skillsinc.readers:PackageReader", group
            ),
        )
