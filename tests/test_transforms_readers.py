"""Ordered transformation and complete package interpretation contracts."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from agentsync.config import Step
from agentsync.exceptions import ConfigurationError
from agentsync.jsonutil import Json, JsonObject
from agentsync.models import Customization, PackageFile, Snapshot
from agentsync.readers import Frontmatter, PackageReader
from agentsync.transforms import (
    BuiltinTransform,
    ExecutableTransform,
    Selection,
    TransformRegistry,
)


class TestTransformations:
    """Collection operations retain configured ordering."""

    def test_external_preserves_origins_and_executable_files(self) -> None:
        """External conversion preserves identity and POSIX permissions."""
        item = Customization(
            "script",
            "hooks",
            (PackageFile("script.sh", b"exit 0", 0o755),),
            {},
            origins=("local:hooks/script",),
        )
        code = "import sys,json; sys.stdout.write(json.dumps(json.load(sys.stdin)))"
        output = ExecutableTransform().apply(
            (item,), {"argv": [sys.executable, "-c", code]}
        )[0]
        assert output.origins == item.origins
        assert output.files[0].content == b"exit 0"
        if os.name != "nt":
            assert output.files[0].mode == 0o755

    def item(self) -> Customization:
        """Create a portable Markdown customization."""
        return Customization(
            "old-name",
            "instructions",
            (PackageFile("rule.md", b"hello old"),),
            {"keep": True},
            source="test",
        )

    @pytest.mark.parametrize(
        ("name", "options", "expected"),
        [
            ("prefix", {"remove": "old-", "add": "new-"}, "new-name"),
            ("rename", {"names": {"old-name": "renamed"}}, "renamed"),
        ],
        ids=["prefix", "rename"],
    )
    def test_name_changes(self, name: str, options: object, expected: str) -> None:
        """Names change only by explicit transformations."""
        assert (
            BuiltinTransform(name).apply((self.item(),), Json.record(options))[0].name
            == expected
        )

    @pytest.mark.parametrize(
        ("name", "options"),
        [
            ("select", {"patterns": ["missing"]}),
            ("exclude", {"patterns": ["instructions/*"]}),
        ],
        ids=["select", "exclude"],
    )
    def test_zero_results(self, name: str, options: object) -> None:
        """Filtering is an intentional zero-output transformation."""
        assert BuiltinTransform(name).apply((self.item(),), Json.record(options)) == ()

    def test_pipeline_order(self) -> None:
        """An earlier rename influences later selection."""
        steps = (
            Step("prefix", {"add": "team-"}),
            Step("select", {"patterns": ["team-*"]}),
        )
        assert (
            TransformRegistry().apply((self.item(),), steps)[0].name == "team-old-name"
        )

    @pytest.mark.parametrize(
        ("name", "options"),
        [
            ("replace", {"old": "old", "new": "new"}),
            ("metadata", {"set": {"new": 1}, "remove": ["keep"]}),
            ("path-map", {"paths": {"rule.md": "new.md"}}),
            ("format", {"kind": "prompts", "style": "claude"}),
        ],
        ids=["text", "metadata", "paths", "format"],
    )
    def test_content_and_metadata_operations(self, name: str, options: object) -> None:
        """Transformations preserve unmodified package properties."""
        result = BuiltinTransform(name).apply((self.item(),), Json.record(options))[0]
        assert result != self.item()
        assert result.source == "test"

    def test_split_and_compose(self) -> None:
        """One-to-many and many-to-one transformations are supported."""
        split = BuiltinTransform("split").apply(
            (self.item(),), {"names": ["one", "two"]}
        )
        assert len(split) == 2
        composed = BuiltinTransform("compose").apply(split, {"name": "combined"})
        assert composed[0].files[0].content == b"hello old\nhello old"
        assert BuiltinTransform("compose").apply((), {"name": "empty"}) == ()

    def test_unknown_transform_and_selection(self) -> None:
        """Unknown plugins fail and selectors match explicit kind/name."""
        with pytest.raises(ConfigurationError, match="Unknown"):
            TransformRegistry().resolve("not-installed")
        assert Selection.matches(self.item(), ("instructions/*",))
        assert not Selection.matches(self.item(), ("skills/*",))

    def test_external_protocol_round_trip(self) -> None:
        """Trusted subprocess transformations can return staged packages."""
        code = (
            "import sys,json; d=json.load(sys.stdin); d['customizations']["
            "0]['name']='external'; sys.stdout.write(json.dumps(d))"
        )
        options: JsonObject = {"argv": [sys.executable, "-c", code]}
        transformed = ExecutableTransform().apply((self.item(),), options)
        assert transformed[0].name == "external"
        assert transformed[0].files[0].content == b"hello old"

    @pytest.mark.parametrize(
        ("code", "message"),
        [
            ("raise SystemExit(1)", "failed"),
            ("import sys; sys.stdout.write('{}')", "version"),
            ("import sys; sys.stdout.write('x'*5000000)", "limit"),
            (
                (
                    "import sys,json; d=json.load(sys.stdin); d['customizations']"
                    "[0]['package']='C:/outside'; sys.stdout.write(json.dumps(d))"
                ),
                "escapes",
            ),
        ],
        ids=["nonzero", "version", "output-limit", "escape"],
    )
    def test_external_failures(self, code: str, message: str) -> None:
        """Malformed output cannot bypass package containment."""
        with pytest.raises(ConfigurationError, match=message):
            ExecutableTransform().apply(
                (self.item(),), {"argv": [sys.executable, "-c", code]}
            )

    def test_external_missing_argv(self) -> None:
        """Executable extensions require explicit commands."""
        with pytest.raises(ConfigurationError, match="argv"):
            TransformRegistry().resolve("executable").apply((), {"argv": []})


class TestReaders:
    """Reader semantics remain independent from output rendering."""

    def test_complete_skill_package(self, tmp_path: Path) -> None:
        """Supporting files, executable bits, and metadata are retained."""
        snapshot = Snapshot(
            tmp_path,
            "one",
            (
                PackageFile("README.md", b"ignored"),
                PackageFile(
                    "skills/test/SKILL.md",
                    (
                        b"---\nname: test\ndescription: Test skill\n---\nUse reference"
                        b"s/file.md\n"
                    ),
                ),
                PackageFile("skills/test/references/file.md", b"details"),
                PackageFile("skills/test/scripts/run.sh", b"exit 0", 0o755),
            ),
        )
        item = PackageReader().read(snapshot, "test", "portable")[0]
        assert item.kind == "skills"
        assert item.files[-1].mode == 0o755
        assert item.metadata["description"] == "Test skill"

    @pytest.mark.parametrize(
        "content",
        [b"body", b"---\nname: test\n---\nbody"],
        ids=["missing-frontmatter", "missing-description"],
    )
    def test_invalid_skills_block_source(self, tmp_path: Path, content: bytes) -> None:
        """Malformed skills cannot silently vanish and trigger deletion."""
        snapshot = Snapshot(
            tmp_path, "one", (PackageFile("skills/test/SKILL.md", content),)
        )
        with pytest.raises(ConfigurationError, match="Skill"):
            PackageReader().read(snapshot, "test", "portable")

    def test_native_commands_and_path_instructions(self, tmp_path: Path) -> None:
        """Native aliases map into shared semantic kinds."""
        snapshot = Snapshot(
            tmp_path,
            "one",
            (
                PackageFile("commands/review.md", b"review"),
                PackageFile(
                    "instructions/python.instructions.md",
                    b'---\napplyTo: "**/*.py"\n---\nBe strict\n',
                ),
            ),
        )
        items = PackageReader().read(snapshot, "test", "copilot")
        assert {item.kind for item in items} == {"prompts", "instructions"}
        assert (
            next(item for item in items if item.kind == "instructions").name == "python"
        )

    @pytest.mark.parametrize(
        "content",
        [b"---\ninvalid", b"---\ninvalid: [\n---\nbody"],
        ids=["unclosed", "invalid-yaml"],
    )
    def test_frontmatter_errors(self, content: bytes) -> None:
        """Unterminated or invalid metadata is rejected."""
        with pytest.raises(ConfigurationError):
            Frontmatter.read(content)

    def test_frontmatter_plain_and_roundtrip(self) -> None:
        """Plain Markdown remains unchanged without invented metadata."""
        assert Frontmatter.write({}, "body") == b"body"
        assert Frontmatter.read(b"body") == ({}, "body")
        assert Frontmatter.read(Frontmatter.write({"name": "x"}, "body")) == (
            {"name": "x"},
            "body",
        )

    def test_native_root_configuration_import(self, tmp_path: Path) -> None:
        """Root instructions, MCP declarations, and hook entries are imported."""
        snapshot = Snapshot(
            tmp_path,
            "one",
            (
                PackageFile("CLAUDE.md", b"root rules"),
                PackageFile(
                    "settings.json",
                    (
                        b'{"mcpServers":{"tool":{"command":"tool"}},"hooks":{"Stop'
                        b'":[{"command":"stop"}]}}'
                    ),
                ),
            ),
        )
        items = PackageReader().read(snapshot, "native", "claude")
        assert {item.kind for item in items} == {"instructions", "mcp", "hooks"}

    def test_native_codex_agent_import(self, tmp_path: Path) -> None:
        """Native TOML agents retain instructions and metadata."""
        snapshot = Snapshot(
            tmp_path,
            "one",
            (
                PackageFile(
                    "agents/reviewer.toml",
                    (
                        b'description="Review"\ndeveloper_instructions="Be strict"\n'
                        b'sandbox_mode="read-only"\n'
                    ),
                ),
            ),
        )
        item = PackageReader().read(snapshot, "native", "codex")[0]
        assert item.metadata["sandbox_mode"] == "read-only"
        assert Frontmatter.read(item.files[0].content)[1] == "Be strict"
