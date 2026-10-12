"""Configuration versioning, bootstrap, extensions, and path boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.conftest import Sandbox

from skillsinc.config import Configuration
from skillsinc.exceptions import ConfigurationError
from skillsinc.jsonutil import Json
from skillsinc.paths import SafePath, XdgPaths


class TestConfiguration:
    """Configuration errors never mutate source or destination state."""

    def test_initialize_is_idempotent_and_disabled(self, sandbox: Sandbox) -> None:
        """Default targets remain disabled and user edits survive bootstrap."""
        configuration = Configuration(sandbox.paths)
        file = configuration.initialize()
        assert all(not target.enabled for target in configuration.load().destinations)
        file.write_text('{"custom":"preserve"}', encoding="utf-8")
        assert configuration.initialize() == file
        assert file.read_text(encoding="utf-8") == '{"custom":"preserve"}'

    def test_bootstrap_only_default_mutating_commands(self, sandbox: Sandbox) -> None:
        """Explicit config failures cannot create default directories."""
        configuration = Configuration(sandbox.paths)
        with pytest.raises(ConfigurationError, match="missing"):
            configuration.load(sandbox.root / "missing.json", bootstrap=True)
        assert not sandbox.paths.config.exists()
        assert configuration.load(bootstrap=True).sources

    @pytest.mark.parametrize(
        "data",
        [
            {"version": 2},
            {
                "version": 1,
                "routes": [{"name": "x", "sources": ["missing"], "destinations": []}],
            },
            {
                "version": 1,
                "routes": [
                    {"name": "x", "sources": [], "destinations": []},
                    {"name": "x", "sources": [], "destinations": []},
                ],
            },
            {"version": 1, "settings": {"poll": 0}},
            {"version": 1, "destinations": {"x": {"location": "x", "scope": "wrong"}}},
        ],
        ids=["version", "reference", "duplicate", "timer", "scope"],
    )
    def test_invalid_envelope(self, sandbox: Sandbox, data: object) -> None:
        """Invalid core structure is rejected before extension execution."""
        with pytest.raises(ConfigurationError):
            Configuration(sandbox.paths).parse(
                Json.record(data), sandbox.root / "config.json"
            )

    def test_pipelines_expand_in_order_and_preserve_options(
        self, sandbox: Sandbox
    ) -> None:
        """Namespaced plugin settings remain extension-owned."""
        data = Json.record(
            {
                "version": 1,
                "sources": {
                    "x": {
                        "location": "source",
                        "options": {"custom": {"anything": [1, 2]}},
                    }
                },
                "destinations": {"x": {"location": "target"}},
                "pipelines": {
                    "rename": [{"use": "prefix", "options": {"add": "team-"}}]
                },
                "routes": [
                    {
                        "name": "x",
                        "sources": ["x"],
                        "destinations": ["x"],
                        "steps": ["rename", {"use": "metadata"}],
                    }
                ],
            }
        )
        settings = Configuration(sandbox.paths).parse(
            data, sandbox.root / "config.json"
        )
        assert [step.use for step in settings.routes[0].steps] == ["prefix", "metadata"]
        assert settings.sources[0].options == {"custom": {"anything": [1, 2]}}

    @pytest.mark.parametrize(
        "steps",
        [["missing"], [{"use": "missing"}]],
        ids=["named-pipeline", "plugin-name"],
    )
    def test_unknown_pipeline_or_plugin(self, steps: object) -> None:
        """Pipeline expansion rejects unknown names; plugin names stay extensible."""
        if steps == ["missing"]:
            with pytest.raises(ConfigurationError, match="pipeline"):
                Configuration.steps(Json.value(steps))
        else:
            assert Configuration.steps(Json.value(steps))[0].use == "missing"

    def test_invalid_exclusion_policy(self, sandbox: Sandbox) -> None:
        """Only deliberate block/exclude policies are accepted."""
        data = Json.record(
            {
                "version": 1,
                "routes": [
                    {
                        "name": "x",
                        "sources": [],
                        "destinations": [],
                        "unsupported": "guess",
                    }
                ],
            }
        )
        with pytest.raises(ConfigurationError, match="unsupported"):
            Configuration(sandbox.paths).parse(data, sandbox.root / "config.json")


class TestPaths:
    """Portable paths reject dangerous aliases on every platform."""

    @pytest.mark.parametrize(
        "name",
        ["../x", "a/../x", "/x", "C:/x", "con.txt", "a.", "a ", "", "a//b", "a/./b"],
        ids=[
            "parent",
            "embedded-parent",
            "absolute",
            "drive",
            "reserved",
            "dot",
            "space",
            "empty",
            "empty-component",
            "dot-component",
        ],
    )
    def test_reject_unsafe_paths(self, name: str) -> None:
        """No customization filename can escape a declared root."""
        with pytest.raises(ConfigurationError):
            SafePath.relative(name)

    def test_portable_paths_and_relative_configuration(self, sandbox: Sandbox) -> None:
        """Unicode and portable separators resolve consistently."""
        assert SafePath.relative("skills\\日本語\\SKILL.md") == "skills/日本語/SKILL.md"
        assert SafePath.configured("folder", sandbox.root) == sandbox.root / "folder"
        assert SafePath.child(sandbox.root, "a/b.md") == sandbox.root / "a/b.md"

    def test_xdg_absolute_validation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Relative XDG overrides fail rather than resolve unpredictably."""
        monkeypatch.setenv("XDG_CONFIG_HOME", "relative")
        with pytest.raises(ConfigurationError, match="absolute"):
            XdgPaths.discover()

    def test_xdg_unset_fallbacks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unspecified storage follows the requested XDG-style defaults."""
        for variable in (
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_STATE_HOME",
            "XDG_CACHE_HOME",
        ):
            monkeypatch.delenv(variable)
        assert XdgPaths.discover().config == Path.home() / ".config/skillsinc"


class TestJsonBoundary:
    """Untyped data becomes strict recursive JSON values."""

    @pytest.mark.parametrize(
        "value", [object(), {1: "bad"}, (1, 2)], ids=["object", "key", "tuple"]
    )
    def test_reject_non_json_values(self, value: object) -> None:
        """Non-JSON extension output is rejected."""
        with pytest.raises(ConfigurationError):
            Json.value(value)

    @pytest.mark.parametrize(
        ("method", "value"),
        [
            ("loads", "bad"),
            ("object", []),
            ("array", {}),
            ("string", 1),
            ("boolean", 1),
            ("number", False),
            ("number", -1),
        ],
        ids=[
            "loads",
            "object",
            "array",
            "string",
            "boolean",
            "bool-number",
            "negative-number",
        ],
    )
    def test_invalid_boundary_types(self, method: str, value: object) -> None:
        """Type-specific extractors reject incompatible values."""
        with pytest.raises(ConfigurationError):
            getattr(Json, method)(value)


class TestDestinationPipelines:
    """Reusable pipelines expand at their destination-specific position."""

    def test_named_destination_steps(self, tmp_path: Path) -> None:
        """Destination pipelines resolve with the same envelope namespace."""
        paths = XdgPaths.discover()
        data = Json.record(
            {
                "version": 1,
                "pipelines": {
                    "personal": [{"use": "prefix", "options": {"add": "mine-"}}]
                },
                "sources": {},
                "destinations": {
                    "target": {
                        "location": str(tmp_path / "target"),
                        "options": {"steps": ["personal"]},
                    }
                },
                "routes": [],
            }
        )
        settings = Configuration(paths).parse(data, tmp_path / "config.json")
        assert settings.destinations[0].steps[0].use == "prefix"
        assert settings.destinations[0].steps[0].options == {"add": "mine-"}
