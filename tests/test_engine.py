"""End-to-end desired-state convergence and ownership failure tests."""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path
from typing import override

import pytest
from tests.conftest import Sandbox

from skillsinc.config import Configuration, Route, Source
from skillsinc.engine import DistributionPlanner, Engine
from skillsinc.exceptions import ConfigurationError
from skillsinc.jsonutil import Json
from skillsinc.models import PackageFile, Snapshot, SourceProvider


class TestEngine:
    """Verify complete distribution through the public engine."""

    def test_add_update_delete_drift_and_noop(self, sandbox: Sandbox) -> None:
        """Source changes propagate and destination drift is repaired."""
        settings = sandbox.config()
        source = sandbox.put("instructions/rule.md")
        engine = Engine(sandbox.paths)
        target = sandbox.root / "target/instructions/rule/rule.md"
        assert engine.run(settings, apply=True)["ok"] is True
        assert target.read_bytes() == b"hello"
        target.write_bytes(b"drift")
        assert engine.run(settings, apply=True)["ok"] is True
        assert target.read_bytes() == b"hello"
        source.write_bytes(b"changed")
        assert engine.run(settings, apply=True)["ok"] is True
        assert target.read_bytes() == b"changed"
        noop = engine.run(settings)
        assert Json.object(Json.array(noop["targets"])[0])["operations"] == []
        source.unlink()
        assert engine.run(settings, apply=True)["ok"] is True
        assert not target.exists()

    def test_missing_source_never_deletes(self, sandbox: Sandbox) -> None:
        """Unavailable roots retain all last-successful outputs."""
        settings = sandbox.config()
        sandbox.put("instructions/rule.md")
        engine = Engine(sandbox.paths)
        assert engine.run(settings, apply=True)["ok"] is True
        shutil.rmtree(sandbox.root / "source")
        report = engine.run(settings, apply=True)
        assert report["ok"] is False
        assert (sandbox.root / "target/instructions/rule/rule.md").exists()

    def test_unmanaged_collision_and_explicit_adoption(self, sandbox: Sandbox) -> None:
        """Adoption is required even when unmanaged content matches."""
        settings = sandbox.config()
        sandbox.put("instructions/rule.md")
        target = sandbox.root / "target/instructions/rule/rule.md"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"hello")
        engine = Engine(sandbox.paths)
        assert engine.run(settings, apply=True)["ok"] is False
        assert engine.run(settings, apply=True, adopt=True)["ok"] is True
        assert engine.store.records()

    def test_read_only_plan(self, sandbox: Sandbox) -> None:
        """Planning does not create state or output directories."""
        settings = sandbox.config()
        sandbox.put("instructions/rule.md")
        assert Engine(sandbox.paths).run(settings)["ok"] is True
        assert not sandbox.paths.state.exists()
        assert not (sandbox.root / "target").exists()

    def test_removed_route_cleans_only_owned_output(self, sandbox: Sandbox) -> None:
        """Explicit route removal preserves unrelated files."""
        settings = sandbox.config()
        sandbox.put("instructions/rule.md")
        engine = Engine(sandbox.paths)
        engine.run(settings, apply=True)
        unrelated = sandbox.root / "target/unrelated.txt"
        unrelated.write_bytes(b"keep")
        assert engine.run(replace(settings, routes=()), apply=True)["ok"] is True
        assert unrelated.read_bytes() == b"keep"
        assert not (sandbox.root / "target/instructions/rule/rule.md").exists()

    def test_two_configs_cannot_claim_same_output(self, sandbox: Sandbox) -> None:
        """Ownership spans configuration files within the state store."""
        settings = sandbox.config()
        sandbox.put("instructions/rule.md")
        engine = Engine(sandbox.paths)
        assert engine.run(settings, apply=True)["ok"] is True
        other = replace(settings, file=sandbox.root / "different.json")
        assert engine.run(other, apply=True, adopt=True)["ok"] is False

    def test_many_to_many_shared_output(self, sandbox: Sandbox) -> None:
        """Identical overlapping outputs are one connected commit group."""
        destinations = {
            name: {"location": str(sandbox.root / "target"), "enabled": True}
            for name in ("one", "two")
        }
        settings = sandbox.config(destinations=Json.record(destinations))
        sandbox.put("instructions/rule.md")
        report = Engine(sandbox.paths).run(settings, apply=True)
        assert report["ok"] is True
        assert len(Json.array(report["targets"])) == 1
        assert Json.object(Json.array(report["targets"])[0])["names"] == ["one", "two"]

    def test_independent_target_survives_unsupported_conversion(
        self, sandbox: Sandbox
    ) -> None:
        """Only the invalid target is blocked."""
        settings = sandbox.config(
            destinations={
                "good": {"location": str(sandbox.root / "good"), "enabled": True},
                "bad": {
                    "location": str(sandbox.root / "bad"),
                    "enabled": True,
                    "profile": "shared",
                },
            }
        )
        sandbox.put("mcp/tool.json", b'{"command":"example"}')
        report = Engine(sandbox.paths).run(settings, apply=True)
        assert report["ok"] is False
        assert (sandbox.root / "good/mcp/tool/tool.json").exists()
        assert not (sandbox.root / "bad").exists()

    def test_explicit_exclusion(self, sandbox: Sandbox) -> None:
        """Unsupported exclusions are visible and policy controlled."""
        settings = sandbox.config(profile="shared")
        sandbox.put("mcp/tool.json", b'{"command":"example"}')
        settings = replace(
            settings, routes=(replace(settings.routes[0], unsupported="exclude"),)
        )
        report = Engine(sandbox.paths).run(settings, apply=True)
        assert report["ok"] is True
        assert Json.array(report["diagnostics"])

    def test_conflicting_routes_block(self, sandbox: Sandbox) -> None:
        """Different proposed bytes at the same output never overwrite."""
        settings = sandbox.config()
        sandbox.put("instructions/rule.md")
        second = sandbox.root / "second"
        (second / "instructions").mkdir(parents=True)
        (second / "instructions/rule.md").write_bytes(b"different")
        settings = replace(
            settings,
            sources=(*settings.sources, Source("other", str(second))),
            routes=(*settings.routes, Route("other", ("other",), ("target",), ())),
        )
        assert Engine(sandbox.paths).run(settings, apply=True)["ok"] is False

    @pytest.mark.parametrize(
        "relative", ["..", "inside", "."], ids=["ancestor", "descendant", "same"]
    )
    def test_reject_source_destination_overlap(
        self, sandbox: Sandbox, relative: str
    ) -> None:
        """Feedback cycles fail before scanning or writing."""
        settings = sandbox.config()
        destination = replace(
            settings.destinations[0],
            location=Path(settings.sources[0].location) / relative,
        )
        with pytest.raises(ConfigurationError, match="overlap"):
            Engine(sandbox.paths).run(replace(settings, destinations=(destination,)))

    def test_reject_unknown_target(self, sandbox: Sandbox) -> None:
        """Misspelled target selection is an actionable error."""
        with pytest.raises(ConfigurationError, match="Unknown selected"):
            Engine(sandbox.paths).run(sandbox.config(), ("missing",))

    def test_no_targets_is_valid(self, sandbox: Sandbox) -> None:
        """Defaults do not implicitly configure existing harnesses."""
        Configuration(sandbox.paths).initialize()
        assert (
            Engine(sandbox.paths).run(Configuration(sandbox.paths).load())["ok"] is True
        )


class ChangingProvider:
    """Injected stable-to-unstable source for precommit validation."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls = 0

    def snapshot(self) -> Snapshot:
        """Change revision after planning."""
        self.calls += 1
        return Snapshot(
            self.root, str(self.calls), (PackageFile("instructions/rule.md", b"hello"),)
        )


class ChangingPlanner(DistributionPlanner):
    """Test-only public provider injection."""

    def __init__(self, sandbox: Sandbox) -> None:
        super().__init__(sandbox.paths)
        self.changing = ChangingProvider(sandbox.root / "source")

    @override
    def provider(self, source: Source, *, fetch: bool = True) -> SourceProvider:
        """Return the source whose revision changes during planning."""
        assert source.provider == "local"
        assert isinstance(fetch, bool)
        return self.changing


class TestPrecommit:
    """Source preconditions prevent stale converted output."""

    def test_source_revision_rechecked(self, sandbox: Sandbox) -> None:
        """No output is applied after an authoritative revision change."""
        settings = sandbox.config()
        report = Engine(sandbox.paths, ChangingPlanner(sandbox)).run(
            settings, apply=True
        )
        assert report["ok"] is False
        assert not (sandbox.root / "target").exists()
