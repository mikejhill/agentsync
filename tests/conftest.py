"""Isolated user homes and reusable project scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from agentsync.config import Configuration, Settings
from agentsync.jsonutil import Json, JsonObject
from agentsync.paths import XdgPaths


@dataclass(frozen=True, slots=True)
class Sandbox:
    """Temporary sources, destinations, and all XDG storage."""

    root: Path
    paths: XdgPaths

    def config(
        self,
        *,
        profile: str = "generic",
        destinations: JsonObject | None = None,
        steps: list[JsonObject] | None = None,
        style: str = "portable",
    ) -> Settings:
        """Write an explicit configuration without real harness access."""
        source = self.root / "source"
        source.mkdir(exist_ok=True)
        data = Json.record(
            {
                "version": 1,
                "sources": {"local": {"location": str(source), "style": style}},
                "destinations": destinations
                or {
                    "target": {
                        "location": str(self.root / "target"),
                        "enabled": True,
                        "profile": profile,
                        "scope": "project",
                    }
                },
                "routes": [
                    {
                        "name": "default",
                        "sources": ["local"],
                        "destinations": list(destinations)
                        if destinations is not None
                        else ["target"],
                        "steps": steps or [],
                    }
                ],
            }
        )
        self.paths.config.mkdir(parents=True, exist_ok=True)
        file = self.paths.config / "config.json"
        file.write_text(Json.dumps(data), encoding="utf-8")
        return Configuration(self.paths).load(file)

    def put(self, relative: str, content: bytes = b"hello") -> Path:
        """Add one authoritative source file."""
        path = self.root / "source" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent every test from touching real home or harness settings."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    for key, folder in (
        ("XDG_CONFIG_HOME", "config"),
        ("XDG_DATA_HOME", "data"),
        ("XDG_STATE_HOME", "state"),
        ("XDG_CACHE_HOME", "cache"),
    ):
        monkeypatch.setenv(key, str(tmp_path / folder))


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    """Create a complete isolated AgentSync scenario."""
    return Sandbox(tmp_path, XdgPaths.discover())
