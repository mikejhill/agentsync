"""Versioned extensible configuration and default initialization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agentsync.catalog import Catalog
from agentsync.exceptions import ConfigurationError
from agentsync.jsonutil import Json, JsonObject, JsonValue
from agentsync.paths import SafePath, XdgPaths


@dataclass(frozen=True, slots=True)
class Source:
    """Named provider and reader declaration."""

    name: str
    location: str
    provider: str = "local"
    style: str = "portable"
    reader: str = "default"
    options: JsonObject | None = None
    select: tuple[str, ...] = ("*",)


@dataclass(frozen=True, slots=True)
class Destination:
    """Concrete root and optional harness profile."""

    name: str
    location: Path
    profile: str = "generic"
    scope: str = "user"
    enabled: bool = False
    options: JsonObject | None = None
    version: str | None = None
    steps: tuple[Step, ...] = ()


@dataclass(frozen=True, slots=True)
class Step:
    """Ordered transformation and extension-owned settings."""

    use: str
    options: JsonObject


@dataclass(frozen=True, slots=True)
class Route:
    """Many-to-many routing and fidelity policy."""

    name: str
    sources: tuple[str, ...]
    destinations: tuple[str, ...]
    steps: tuple[Step, ...]
    select: tuple[str, ...] = ("*",)
    approximate: bool = False
    unsupported: str = "block"


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved orchestration configuration."""

    file: Path
    sources: tuple[Source, ...]
    destinations: tuple[Destination, ...]
    routes: tuple[Route, ...]
    debounce: float = 0.5
    poll: float = 60
    verify: float = 300
    remote_poll: float = 300


class Configuration:
    """Load policy while leaving plugin payloads extensible."""

    def __init__(self, paths: XdgPaths) -> None:
        self.paths = paths

    def load(self, file: Path | None = None, *, bootstrap: bool = False) -> Settings:
        """Load without mutating read-only commands."""
        selected = file.absolute() if file else self.paths.config / "config.json"
        if not selected.exists() and bootstrap and file is None:
            self.initialize()
        if not selected.is_file():
            raise ConfigurationError(
                f"Configuration missing: {selected}; run agentsync init"
            )
        return self.parse(
            Json.object(Json.loads(selected.read_text(encoding="utf-8"))), selected
        )

    def initialize(self) -> Path:
        """Create defaults once without replacing user configuration."""
        file = self.paths.config / "config.json"
        self.paths.config.mkdir(parents=True, exist_ok=True)
        Catalog.install(self.paths.data)
        if file.exists():
            return file
        for kind in ("skills", "instructions", "agents", "prompts", "hooks", "mcp"):
            (self.paths.config / "customizations" / kind).mkdir(
                parents=True, exist_ok=True
            )
        templates: JsonObject = {}
        for profile, folder in (
            ("shared", ".agents"),
            ("claude", ".claude"),
            ("codex", ".codex"),
            ("codex-desktop", ".codex"),
            ("copilot-cli", ".copilot"),
            ("copilot-vscode", ".copilot"),
            ("cursor-ide", ".cursor"),
            ("cursor-cli", ".cursor"),
            ("gemini", ".gemini"),
            ("opencode", ".config/opencode"),
        ):
            templates[profile] = {
                "location": str(Path.home() / folder),
                "profile": profile,
                "enabled": False,
            }
        default = Json.record(
            {
                "version": 1,
                "sources": {"personal": {"location": "customizations"}},
                "destinations": templates,
                "routes": [
                    {
                        "name": profile,
                        "sources": ["personal"],
                        "destinations": [profile],
                        "select": self._default_selection(profile),
                    }
                    for profile in templates
                ],
                "pipelines": {},
                "settings": {
                    "debounce": 0.5,
                    "poll": 60,
                    "verify": 300,
                    "remote_poll": 300,
                },
            }
        )
        try:
            with file.open("x", encoding="utf-8") as stream:
                stream.write(Json.dumps(default))
        except FileExistsError:
            return file
        return file

    @staticmethod
    def _default_selection(profile: str) -> list[str]:
        """Make default recipe capability selection explicit and editable."""
        kinds = {
            "shared": ["skills"],
            "codex": ["instructions", "agents", "prompts", "mcp", "hooks"],
            "codex-desktop": ["instructions", "agents", "prompts", "mcp", "hooks"],
            "copilot-cli": ["skills", "instructions", "agents", "mcp", "hooks"],
            "copilot-vscode": ["skills", "instructions", "agents", "hooks", "mcp"],
            "gemini": ["skills", "instructions", "prompts", "mcp", "hooks"],
            "opencode": ["skills", "instructions", "agents", "prompts", "mcp"],
            "cursor-ide": ["skills", "agents", "prompts", "hooks", "mcp"],
            "cursor-cli": ["skills", "agents", "prompts", "hooks", "mcp"],
        }.get(profile)
        return [kind + "/*" for kind in kinds] if kinds is not None else ["*"]

    def parse(self, data: JsonObject, file: Path) -> Settings:
        """Validate references and create typed settings."""
        if data.get("version") != 1:
            raise ConfigurationError("Unsupported configuration version; expected 1")
        sources = tuple(
            self._source(name, Json.object(value), file.parent)
            for name, value in Json.object(data.get("sources", {})).items()
        )
        pipelines = Json.object(data.get("pipelines", {}))
        destinations = tuple(
            self._destination(name, Json.object(value), file.parent, pipelines)
            for name, value in Json.object(data.get("destinations", {})).items()
        )
        routes = tuple(
            self._route(Json.object(value), pipelines)
            for value in Json.array(data.get("routes", []))
        )
        names = [route.name for route in routes]
        if len(set(names)) != len(names):
            raise ConfigurationError("Route names must be unique")
        for route in routes:
            if set(route.sources) - {source.name for source in sources} or set(
                route.destinations
            ) - {destination.name for destination in destinations}:
                raise ConfigurationError(f"Unknown reference in route {route.name}")
        timers = Json.object(data.get("settings", {}))
        return Settings(
            file,
            sources,
            destinations,
            routes,
            *(
                Json.number(timers.get(key, default))
                for key, default in (
                    ("debounce", 0.5),
                    ("poll", 60),
                    ("verify", 300),
                    ("remote_poll", 300),
                )
            ),
        )

    @staticmethod
    def _source(name: str, value: JsonObject, base: Path) -> Source:
        """Parse local paths or remote URLs."""
        provider = Json.string(value.get("provider", "local"))
        raw = Json.string(value.get("location"))
        location = str(SafePath.configured(raw, base)) if provider == "local" else raw
        return Source(
            name,
            location,
            provider,
            Json.string(value.get("style", "portable")),
            Json.string(value.get("reader", "default")),
            Json.object(value.get("options", {})),
            Json.strings(value.get("select", ["*"])),
        )

    @classmethod
    def _destination(
        cls, name: str, value: JsonObject, base: Path, pipelines: JsonObject
    ) -> Destination:
        """Parse destination policy."""
        scope = Json.string(value.get("scope", "user"))
        if scope not in ("user", "project"):
            raise ConfigurationError("Destination scope must be user or project")
        version = value.get("version")
        return Destination(
            name,
            SafePath.configured(Json.string(value.get("location")), base),
            Json.string(value.get("profile", "generic")),
            scope,
            Json.boolean(value.get("enabled", False)),
            Json.object(value.get("options", {})),
            Json.string(version) if version is not None else None,
            cls.steps(
                Json.object(value.get("options", {})).get("steps", []), pipelines
            ),
        )

    @classmethod
    def _route(cls, value: JsonObject, pipelines: JsonObject) -> Route:
        """Expand named pipelines in place."""
        unsupported = Json.string(value.get("unsupported", "block"))
        if unsupported not in ("block", "exclude"):
            raise ConfigurationError("unsupported must be block or exclude")
        return Route(
            Json.string(value.get("name")),
            Json.strings(value.get("sources")),
            Json.strings(value.get("destinations")),
            cls.steps(value.get("steps", []), pipelines),
            Json.strings(value.get("select", ["*"])),
            Json.boolean(value.get("allow_approximate", False)),
            unsupported,
        )

    @classmethod
    def steps(
        cls, value: JsonValue, pipelines: JsonObject | None = None
    ) -> tuple[Step, ...]:
        """Resolve steps without recursive expansion."""
        result = []
        for raw in Json.array(value):
            if isinstance(raw, str):
                named = (pipelines or {}).get(raw)
                if named is None:
                    raise ConfigurationError(f"Unknown or recursive pipeline {raw}")
                result.extend(cls.steps(named))
            else:
                step = Json.object(raw)
                result.append(
                    Step(
                        Json.string(step.get("use")),
                        Json.object(step.get("options", {})),
                    )
                )
        return tuple(result)
