"""Independent failure boundaries for caching, fidelity, and background lifecycle."""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import override

import pytest
from hypothesis import given
from hypothesis import strategies as st
from tests.conftest import Sandbox
from watchdog.events import FileModifiedEvent, FileOpenedEvent, FileSystemEventHandler
from watchdog.observers.api import BaseObserver, ObservedWatch

from agentsync.__main__ import Application
from agentsync.cache import ConversionCache
from agentsync.config import Destination, Settings
from agentsync.contracts import HarnessRenderer
from agentsync.documents import Documents
from agentsync.engine import DistributionPlanner, Engine
from agentsync.exceptions import (
    ConfigurationError,
    ConflictError,
    ConversionError,
    SourceError,
)
from agentsync.hooks import HookPolicy
from agentsync.jsonutil import Json, JsonObject, JsonValue
from agentsync.models import Customization, Output, PackageFile
from agentsync.readers import PackageReader
from agentsync.service_runner import ServiceRunner
from agentsync.sources import GitSource, LocalSource
from agentsync.transactions import TransactionManager
from agentsync.transforms import ExecutableTransform
from agentsync.watch import ChangeHandler, WatchCoordinator


class TestHardening:
    """Regression coverage exercises public behavior rather than helper duplication."""

    def test_read_only_remote_does_not_create_cache(self, sandbox: Sandbox) -> None:
        """Absent mirrors require an explicit mutating fetch."""
        source = replace(sandbox.config().sources[0], provider="git")
        with pytest.raises(SourceError, match="sync"):
            GitSource(source, sandbox.paths.cache, fetch=False).snapshot()
        assert not sandbox.paths.cache.exists()

    def test_cached_render_repairs_drift_and_changed_input(
        self, sandbox: Sandbox
    ) -> None:
        """Cache hits still reconcile ownership and source revisions."""
        settings = sandbox.config()
        file = sandbox.put("instructions/rule.md", b"first")
        engine = Engine(sandbox.paths)
        assert engine.run(settings, apply=True)["ok"] is True
        assert list((sandbox.paths.cache / "conversions").glob("*.json"))
        target = sandbox.root / "target/instructions/rule/rule.md"
        target.write_bytes(b"drift")
        assert engine.run(settings, apply=True)["ok"] is True
        assert target.read_bytes() == b"first"
        file.write_bytes(b"second")
        assert engine.run(settings, apply=True)["ok"] is True
        assert target.read_bytes() == b"second"

    def test_selected_alias_removal_retains_other_route(self, sandbox: Sandbox) -> None:
        """Removing a shared-root route cannot delete another route's output."""
        settings = sandbox.config()
        first = replace(settings.destinations[0], name="a")
        second = replace(first, name="b")
        route = replace(settings.routes[0], destinations=("a", "b"))
        settings = replace(settings, destinations=(first, second), routes=(route,))
        sandbox.put("instructions/rule.md", b"owned")
        engine = Engine(sandbox.paths)
        assert engine.run(settings, apply=True)["ok"] is True
        settings = replace(settings, routes=(replace(route, destinations=("a",)),))
        assert engine.run(settings, ("b",), apply=True)["ok"] is True
        assert (
            sandbox.root / "target/instructions/rule/rule.md"
        ).read_bytes() == b"owned"

    def test_mcp_override_cannot_create_source_cycle(self, sandbox: Sandbox) -> None:
        """Native sibling files must pass source/output cycle checks."""
        settings = sandbox.config()
        destination = replace(
            settings.destinations[0],
            profile="codex",
            options={"mcp_file": str(sandbox.root / "source/config.toml")},
        )
        sandbox.put("mcp/tool.json", b'{"command":"tool"}')
        report = Engine(sandbox.paths).run(
            replace(settings, destinations=(destination,)), apply=True
        )
        assert report["ok"] is False
        assert not (sandbox.root / "source/config.toml").exists()

    @pytest.mark.parametrize("profile", ["shared", "cursor-ide", "cursor-cli"])
    def test_unknown_global_instruction_discovery_is_blocked(
        self, sandbox: Sandbox, profile: str
    ) -> None:
        """User scope cannot invent global filesystem activation paths."""
        item = Customization(
            "x", "instructions", (PackageFile("x.md", b"instructions"),), {}
        )
        with pytest.raises(ConversionError):
            HarnessRenderer(Destination("x", sandbox.root, profile)).render(item)

    def test_native_mcp_conversion_through_shared_fields(
        self, sandbox: Sandbox
    ) -> None:
        """OpenCode command arrays convert to Codex stdio without dropping env."""
        item = Customization(
            "server",
            "mcp",
            (),
            {
                "type": "local",
                "command": ["python", "server.py"],
                "environment": {"TOKEN": "${TOKEN}"},
            },
            "opencode",
        )
        output = HarnessRenderer(Destination("x", sandbox.root, "codex")).render(item)[
            0
        ]
        assert Json.loads(output.content.decode()) == {
            "command": "python",
            "args": ["server.py"],
            "env": {"TOKEN": "${TOKEN}"},
        }

    def test_internal_watcher_state_does_not_trigger_feedback(
        self, sandbox: Sandbox
    ) -> None:
        """Status/ownership writes under an observed parent are ignored."""
        changed = Event()
        handler = ChangeHandler(changed, (sandbox.paths.state,))
        handler.on_any_event(
            FileModifiedEvent(str(sandbox.paths.state / "status.json"))
        )
        assert not changed.is_set()

    @pytest.mark.parametrize("content", ["{", '{"version":2}', '{"version":1}'])
    def test_invalid_cache_is_disposable(self, sandbox: Sandbox, content: str) -> None:
        """Corruption cannot create an authoritative destination deletion."""
        cache = ConversionCache(sandbox.paths.cache)
        cache.root.mkdir(parents=True)
        (cache.root / "key.json").write_text(content, encoding="utf-8")
        assert cache.get("key") is None

    def test_cache_integrity_and_binary_content(self, sandbox: Sandbox) -> None:
        """Binary output survives cache encoding; changed encoded bytes are rejected."""
        cache = ConversionCache(sandbox.paths.cache)
        output = Output(sandbox.root / "target/x", b"\x00\xff", "target", ("source",))
        cache.put("key", (output,), ["note"])
        assert cache.get("key") == ((output,), ["note"])
        file = cache.root / "key.json"
        data = Json.object(Json.loads(file.read_text(encoding="utf-8")))
        data["outputs"] = []
        file.write_text(Json.dumps(data), encoding="utf-8")
        assert cache.get("key") is None

    def test_proposed_parent_slot_conflict(self, sandbox: Sandbox) -> None:
        """A whole-file writer and an entry writer cannot share one document."""
        path = sandbox.root / "target/settings.json"
        outputs = (
            Output(path, b"{}", "a", ()),
            Output(path, b"1", "b", (), ("entry",), "json"),
        )
        plan = DistributionPlanner._deduplicate(outputs, {}, {}, ())
        assert set(plan.blocked) == {"a", "b"}

    def test_approximate_conversion_has_reported_diagnostic(
        self, sandbox: Sandbox
    ) -> None:
        """Explicit permission cannot hide semantic degradation from plan output."""
        settings = sandbox.config()
        destination = replace(settings.destinations[0], profile="codex")
        route = replace(settings.routes[0], approximate=True)
        sandbox.put("instructions/rule.md", b"---\napplyTo: '**/*.py'\n---\nBe strict")
        report = Engine(sandbox.paths).run(
            replace(settings, destinations=(destination,), routes=(route,))
        )
        assert report["ok"] is True
        assert "Approximate" in Json.dumps(report["diagnostics"])
        target = Json.object(Json.array(report["targets"])[0])
        assert "AGENTS.md" in Json.dumps(target["outputs"])

    @pytest.mark.parametrize(
        ("version", "runtime", "error"),
        [
            (">=2", None, ConfigurationError),
            (">=2", "1.0", ConversionError),
            ("invalid", "2.0", ConfigurationError),
            (">=2", "bad", ConfigurationError),
        ],
    )
    def test_harness_version_constraints(
        self,
        sandbox: Sandbox,
        version: str,
        runtime: str | None,
        error: type[Exception],
    ) -> None:
        """Unknown runtime evidence and mismatched versions block conversion."""
        options: JsonObject = (
            {"runtime_version": runtime} if runtime is not None else {}
        )
        with pytest.raises(error):
            HarnessRenderer(
                Destination(
                    "x", sandbox.root, "claude", options=options, version=version
                )
            )

    def test_version_and_supporting_files(self, sandbox: Sandbox) -> None:
        """Supported version policy preserves relative dependencies and permissions."""
        renderer = HarnessRenderer(
            Destination(
                "x",
                sandbox.root,
                "claude",
                options={"runtime_version": "2.0"},
                version=">=2",
            )
        )
        item = Customization(
            "x",
            "prompts",
            (
                PackageFile("x.md", b"Read references/x.md"),
                PackageFile("references/x.md", b"details", 0o755),
            ),
            {},
        )
        outputs = renderer.render(item)
        assert outputs[1].path == sandbox.root / "commands/references/x.md"
        assert outputs[1].mode == 0o755

    def test_claude_user_mcp_owned_native_file(self, sandbox: Sandbox) -> None:
        """Personal MCP retains credential references in its native sibling file."""
        destination = Destination("claude", sandbox.root / ".claude", "claude")
        item = Customization(
            "server", "mcp", (), {"command": "tool", "env": {"TOKEN": "${TOKEN}"}}
        )
        output = HarnessRenderer(destination).render(item)[0]
        assert output.path == sandbox.root / ".claude.json"
        assert output.slot == ("mcpServers", "server")
        assert b"${TOKEN}" in output.content

    def test_malformed_native_source_blocks_target(self, sandbox: Sandbox) -> None:
        """TOML parser errors retain previous output instead of escaping the engine."""
        settings = sandbox.config()
        sandbox.put("agents/broken.toml", b"invalid=")
        report = Engine(sandbox.paths).run(settings, apply=True)
        assert report["ok"] is False
        assert "Invalid native" in Json.dumps(report)

    def test_executable_timeout_is_bounded(self) -> None:
        """A hung plugin is killed and its pipes are joined."""
        with pytest.raises(ConfigurationError, match="timed out"):
            ExecutableTransform().apply(
                (),
                {
                    "argv": [sys.executable, "-c", "import time;time.sleep(30)"],
                    "timeout": 0.05,
                },
            )

    @pytest.mark.parametrize(
        ("family", "event", "handlers"),
        [
            ("cursor", "Stop", []),
            ("claude", "Stop", [{"command": "x"}]),
            ("copilot", "preToolUse", [{"type": "invalid"}]),
            ("cursor", "stop", [{}]),
        ],
    )
    def test_invalid_native_hooks(
        self, family: str, event: str, handlers: list[JsonValue]
    ) -> None:
        """Event aliases and malformed command payloads cannot silently pass."""
        with pytest.raises(ConversionError):
            HookPolicy.validate(family, event, handlers)

    @pytest.mark.parametrize(
        ("family", "entry"),
        [
            ("claude", {"type": "prompt", "prompt": "review"}),
            ("cursor", {"type": "prompt", "command": "review"}),
            ("copilot", {"type": "http", "url": "https://example.invalid"}),
        ],
    )
    def test_prompt_and_http_hook_shapes(self, family: str, entry: JsonObject) -> None:
        """Native declared payloads are retained without execution."""
        HookPolicy._handler(family, entry)

    def test_primary_manifest_not_supporting_file(self, sandbox: Sandbox) -> None:
        """Alphabetically earlier supporting files cannot displace the main prompt."""
        sandbox.put("prompts/test/a.txt", b"asset")
        sandbox.put("prompts/test/test.md", b"---\ndescription: Prompt\n---\nRun")
        snapshot = LocalSource(sandbox.root / "source").snapshot()
        item = PackageReader().read(snapshot, "source", "portable")[0]
        assert item.files[0].path == "test.md"
        assert item.metadata["description"] == "Prompt"

    def test_background_environment_runner(
        self, sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Login startup restores XDG roots before composing the regular CLI."""
        environment = sandbox.root / "environment.json"
        environment.write_text(
            json.dumps(
                {"XDG_CONFIG_HOME": str(sandbox.root / "cfg"), "UNRELATED": "ignored"}
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            sys, "argv", ["runner", str(environment), "contracts", "list"]
        )
        with pytest.raises(SystemExit) as result:
            ServiceRunner.main()
        assert result.value.code == 0


class ImmediateStop(Event):
    """Terminate the injected foreground loop without real sleeping."""

    @override
    def wait(self, timeout: float | None = None) -> bool:
        """Verify idle-loop interval and stop after initial reconciliation."""
        assert timeout == 0.1
        return True


class FakeObserver(BaseObserver):
    """Retain watchdog scheduling behavior without starting native threads."""

    def __init__(self) -> None:
        self.scheduled: list[str] = []

    @override
    def start(self) -> None:
        """No real background processes are started by ordinary tests."""

    @override
    def stop(self) -> None:
        """No worker requires termination."""

    @override
    def join(self, timeout: float | None = None) -> None:
        """Check bounded thread shutdown."""
        assert timeout == 5

    @override
    def unschedule_all(self) -> None:
        """Replace the subscription set."""
        self.scheduled.clear()

    @override
    def schedule(
        self,
        event_handler: FileSystemEventHandler,
        path: str,
        *,
        recursive: bool = False,
        event_filter: object = None,
    ) -> ObservedWatch:
        """Record roots and enforce recursive event observation."""
        assert isinstance(event_handler, ChangeHandler)
        assert recursive
        assert event_filter is None
        self.scheduled.append(path)
        return ObservedWatch(path, recursive=recursive)


class TestWatcherLifecycle:
    """Foreground subscriptions and heartbeat shutdown stay within isolated roots."""

    def test_events_and_loop_shutdown(
        self, sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Read events are ignored; writes trigger and shutdown records health."""
        settings: Settings = sandbox.config()
        sandbox.put("instructions/rule.md")
        observer = FakeObserver()
        monkeypatch.setattr("agentsync.watch.Observer", lambda: observer)
        watcher = WatchCoordinator(sandbox.paths, settings.file)
        watcher.stop = ImmediateStop()
        handler = ChangeHandler(watcher.changed)
        handler.on_any_event(FileOpenedEvent(str(sandbox.root)))
        assert not watcher.changed.is_set()
        handler.on_any_event(FileModifiedEvent(str(sandbox.root)))
        assert watcher.changed.is_set()
        watcher.run()
        assert str(sandbox.root / "source") in observer.scheduled
        assert watcher.engine.store.watcher()["state"] == "stopped"
        watcher._terminate(15, None)
        assert watcher.stop.is_set()


class TestPreservationProperties:
    """Randomized unrelated entries survive owned updates and deletions."""

    @given(
        st.dictionaries(
            st.text(alphabet="abcdef", min_size=1, max_size=8),
            st.integers(),
            max_size=15,
        )
    )
    def test_json_deletion_boundary(self, unrelated: dict[str, int]) -> None:
        """An owned nested member can never delete unrelated configuration."""
        before = json.dumps({"unrelated": unrelated}).encode()
        updated = Documents.edit(before, "json", ("owned", "x"), b"1")
        removed = Documents.edit(updated, "json", ("owned", "x"), None)
        assert json.loads(removed)["unrelated"] == unrelated


class TestFinalBoundaries:
    """Preserve native activation and complete-source semantics."""

    def test_human_explain_exposes_pipeline(
        self, sandbox: Sandbox, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An operator can locate the original customization after a rename."""
        settings = sandbox.config(
            steps=[{"use": "prefix", "options": {"add": "mine-"}}]
        )
        sandbox.put("instructions/rule.md", b"Rule")
        assert (
            Application().run(
                ["explain", "mine-rule", "--config-file", str(settings.file)]
            )
            == 0
        )
        output = capsys.readouterr().out
        assert "input:local:instructions/rule" in output
        assert "transform:1:prefix" in output
        assert "contract:generic@1" in output

    def test_transform_trace_preserves_original_identity(
        self, sandbox: Sandbox
    ) -> None:
        """Renaming does not replace the original source identity in explanation."""
        settings = sandbox.config(
            steps=[{"use": "prefix", "options": {"add": "mine-"}}]
        )
        sandbox.put("instructions/rule.md", b"Rule")
        report = Engine(sandbox.paths).run(settings)
        target = Json.object(Json.array(report["targets"])[0])
        output = Json.object(Json.array(target["outputs"])[0])
        assert "input:local:instructions/rule" in Json.strings(output["provenance"])
        assert "transform:1:prefix" in Json.strings(output["provenance"])

    def test_junctions_block_source_and_destination(
        self, sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The Windows junction boundary receives the same checks as symlinks."""
        sandbox.config()
        sandbox.put("linked/file.md")
        monkeypatch.setattr(Path, "is_junction", lambda path: path.name == "linked")
        with pytest.raises(SourceError, match="link"):
            LocalSource(sandbox.root / "source").snapshot()
        with pytest.raises(ConflictError, match="symlink"):
            TransactionManager.write(sandbox.root / "linked/out.md", b"test", 0o644)

    def test_gitlink_is_incomplete(
        self, sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A Git archive cannot silently substitute empty directories for submodules."""
        source = replace(sandbox.config().sources[0], provider="git")
        monkeypatch.setattr(
            GitSource,
            "_git",
            lambda *_arguments: b"160000 commit deadbeef\tskills/shared\0",
        )
        with pytest.raises(SourceError, match="incomplete"):
            GitSource(source, sandbox.paths.cache)._validate_tree("deadbeef")

    @pytest.mark.parametrize(
        "metadata", [{"excludeAgent": "code-review"}, {"description": "Load on demand"}]
    )
    def test_instruction_activation_loss_requires_policy(
        self, sandbox: Sandbox, metadata: JsonObject
    ) -> None:
        """Native relevance and exclusions cannot silently become global guidance."""
        item = Customization(
            "rule",
            "instructions",
            (PackageFile("rule.md", b"Rule"),),
            metadata,
            "copilot",
        )
        destination = Destination("test", sandbox.root / "target", "claude")
        with pytest.raises(ConversionError, match="Approximate"):
            HarnessRenderer(destination).render(item)
        assert HarnessRenderer(destination, approximate=True).render(item)

    @pytest.mark.parametrize(
        ("kind", "file"), [("agents", "review.agent.md"), ("prompts", "run.prompt.md")]
    )
    def test_native_identity_suffixes(
        self, sandbox: Sandbox, kind: str, file: str
    ) -> None:
        """Native format suffixes are removed from semantic identities exactly once."""
        sandbox.config()
        sandbox.put(f"{kind}/{file}", b"---\ndescription: Test\n---\nRun")
        snapshot = LocalSource(sandbox.root / "source").snapshot()
        items = PackageReader().read(snapshot, "local", "copilot-vscode")
        assert items[0].name == file.split(".", maxsplit=1)[0]
