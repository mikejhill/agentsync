"""Independent expected paths, payloads, and fidelity cases per harness."""

from __future__ import annotations

from pathlib import Path

import pytest
import tomlkit

from skillsinc.config import Destination
from skillsinc.contracts import ContractRegistry, HarnessRenderer
from skillsinc.exceptions import ConfigurationError, ConversionError
from skillsinc.jsonutil import Json, JsonValue
from skillsinc.models import Customization, PackageFile
from skillsinc.readers import Frontmatter


class TestHarnessContracts:
    """Hand-authored expectations are independent of renderer tables."""

    @pytest.mark.parametrize("variant", ["agent-host", "local"])
    def test_vscode_session_mcp_locations(self, tmp_path: Path, variant: str) -> None:
        """Native Copilot documents and legacy Local schemas remain distinct."""
        item = Customization("tool", "mcp", (), {"command": "tool"})
        destination = Destination(
            "test",
            tmp_path / ".github",
            "copilot-vscode",
            "project",
            options={"variant": variant},
        )
        output = HarnessRenderer(destination).render(item)[0]
        expected = ".mcp.json" if variant == "agent-host" else ".vscode/mcp.json"
        assert output.path == tmp_path / expected
        assert output.slot == (
            ("mcpServers" if variant == "agent-host" else "servers"),
            "tool",
        )

    def test_vscode_agent_host_rejects_prompt_files(self, tmp_path: Path) -> None:
        """Prompt files cannot claim activation in Agent Host sessions."""
        item = Customization("run", "prompts", (PackageFile("run.md", b"Run"),), {})
        with pytest.raises(ConversionError, match="Agent Host"):
            HarnessRenderer(Destination("x", tmp_path, "copilot-vscode")).render(item)
        with pytest.raises(ConfigurationError, match="variant"):
            HarnessRenderer(
                Destination(
                    "x", tmp_path, "copilot-vscode", options={"variant": "unknown"}
                )
            )

    @pytest.mark.parametrize(
        ("profile", "expected"),
        [
            ("claude", "CLAUDE.md"),
            ("codex", "AGENTS.md"),
            ("codex-desktop", "AGENTS.md"),
            ("copilot-cli", "copilot-instructions.md"),
            ("copilot-vscode", "copilot-instructions.md"),
            ("cursor-ide", "AGENTS.md"),
            ("cursor-cli", "AGENTS.md"),
            ("gemini", "GEMINI.md"),
            ("opencode", "AGENTS.md"),
            ("shared", "AGENTS.md"),
        ],
        ids=[
            "claude",
            "codex-cli",
            "codex-desktop",
            "copilot-cli",
            "copilot-vscode",
            "cursor-ide",
            "cursor-cli",
            "gemini",
            "opencode",
            "shared",
        ],
    )
    def test_instruction_discovery_paths(
        self, tmp_path: Path, profile: str, expected: str
    ) -> None:
        """Each profile uses its independently documented instruction filename."""
        destination = Destination("test", tmp_path, profile, "project", enabled=True)
        item = Customization(
            "rule", "instructions", (PackageFile("rule.md", b"be precise"),), {}
        )
        output = HarnessRenderer(destination).render(item)[0]
        assert output.path == tmp_path / expected
        assert output.slot == ("rule",)
        assert output.content == b"be precise"

    @pytest.mark.parametrize(
        ("profile", "path", "slot"),
        [
            ("codex", "config.toml", "mcp_servers"),
            ("copilot-cli", "mcp-config.json", "mcpServers"),
            ("copilot-vscode", ".mcp.json", "mcpServers"),
            ("cursor-ide", "mcp.json", "mcpServers"),
            ("cursor-cli", "mcp.json", "mcpServers"),
            ("gemini", "settings.json", "mcpServers"),
            ("opencode", "opencode.jsonc", "mcp"),
            ("claude", ".mcp.json", "mcpServers"),
        ],
        ids=[
            "codex",
            "copilot-cli",
            "vscode",
            "cursor-ide",
            "cursor-cli",
            "gemini",
            "opencode",
            "claude",
        ],
    )
    def test_mcp_native_slots(
        self, tmp_path: Path, profile: str, path: str, slot: str
    ) -> None:
        """MCP entries merge by server name into correct native documents."""
        item = Customization(
            "tool",
            "mcp",
            (),
            {"command": "tool", "args": ["serve"], "env": {"TOKEN": "${TOKEN}"}},
        )
        output = HarnessRenderer(
            Destination("test", tmp_path, profile, "project", enabled=True)
        ).render(item)[0]
        assert output.path == tmp_path / path
        assert output.slot == (slot, "tool")
        assert "${TOKEN}" in output.content.decode()

    def test_copilot_scoped_rules_to_claude(self, tmp_path: Path) -> None:
        """Path matching stays scoped in Claude rule frontmatter."""
        item = Customization(
            "python",
            "instructions",
            (PackageFile("python.md", b"strict"),),
            {"applyTo": "**/*.py,tests/**"},
            "copilot",
        )
        output = HarnessRenderer(Destination("test", tmp_path, "claude")).render(item)[
            0
        ]
        assert output.path == tmp_path / "rules/python.md"
        assert Frontmatter.read(output.content) == (
            {"paths": ["**/*.py", "tests/**"]},
            "strict",
        )

    @pytest.mark.parametrize(
        "profile",
        ["copilot-cli", "copilot-vscode", "cursor-ide"],
        ids=["copilot-cli", "vscode", "cursor"],
    )
    def test_native_scoped_instruction_formats(
        self, tmp_path: Path, profile: str
    ) -> None:
        """Scoped instruction profiles produce validated frontmatter."""
        item = Customization(
            "python",
            "instructions",
            (PackageFile("python.md", b"strict"),),
            {"paths": ["**/*.py"]},
        )
        assert (
            HarnessRenderer(Destination("x", tmp_path, profile, scope="project"))
            .render(item)[0]
            .content.startswith(b"---")
        )

    def test_scoping_loss_requires_permission(self, tmp_path: Path) -> None:
        """Unsupported path semantics block rather than silently become global."""
        item = Customization(
            "python",
            "instructions",
            (PackageFile("python.md", b"strict"),),
            {"applyTo": "**/*.py"},
        )
        renderer = HarnessRenderer(Destination("x", tmp_path, "codex"))
        with pytest.raises(ConversionError, match="Approximate"):
            renderer.render(item)
        assert HarnessRenderer(renderer.destination, approximate=True).render(item)

    def test_claude_agent_to_codex(self, tmp_path: Path) -> None:
        """Equivalent basic agent definitions produce native TOML."""
        item = Customization(
            "review",
            "agents",
            (PackageFile("review.md", b"Review code"),),
            {"description": "Code reviewer"},
            "claude",
        )
        output = HarnessRenderer(Destination("x", tmp_path, "codex")).render(item)[0]
        parsed = tomlkit.parse(output.content.decode())
        assert parsed["name"] == "review"
        assert parsed["developer_instructions"] == "Review code"
        assert output.path == tmp_path / "agents/review.toml"

    @pytest.mark.parametrize(
        "profile",
        ["claude", "copilot-cli", "copilot-vscode", "cursor-ide", "opencode"],
        ids=["claude", "copilot-cli", "vscode", "cursor", "opencode"],
    )
    def test_basic_markdown_agents(self, tmp_path: Path, profile: str) -> None:
        """Supported agent surfaces receive native Markdown declarations."""
        item = Customization(
            "review",
            "agents",
            (PackageFile("review.md", b"Review"),),
            {"description": "Review"},
        )
        output = HarnessRenderer(
            Destination(
                "x", tmp_path, profile, scope="project", options={"variant": "local"}
            ),
            approximate=profile == "copilot-vscode",
        ).render(item)[0]
        assert Frontmatter.read(output.content)[0]["description"] == "Review"

    def test_agent_permission_loss_is_explicit(self, tmp_path: Path) -> None:
        """Dropping Claude tool restrictions requires approximation policy."""
        item = Customization(
            "review",
            "agents",
            (PackageFile("review.md", b"Review"),),
            {"description": "Review", "tools": ["Read"]},
            "claude",
        )
        renderer = HarnessRenderer(Destination("x", tmp_path, "codex"))
        with pytest.raises(ConversionError, match="permissions"):
            renderer.render(item)
        assert HarnessRenderer(renderer.destination, approximate=True).render(item)

    @pytest.mark.parametrize(
        ("profile", "expected"),
        [
            ("claude", "commands/review.md"),
            ("codex", "prompts/review.md"),
            ("copilot-vscode", "prompts/review.prompt.md"),
            ("cursor-ide", "commands/review.md"),
            ("opencode", "commands/review.md"),
            ("gemini", "commands/review.toml"),
        ],
        ids=["claude", "codex", "vscode", "cursor", "opencode", "gemini"],
    )
    def test_prompt_conversion(
        self, tmp_path: Path, profile: str, expected: str
    ) -> None:
        """Invocable prompt formats retain text and map Gemini arguments."""
        item = Customization(
            "review", "prompts", (PackageFile("review.md", b"Review $ARGUMENTS"),), {}
        )
        output = HarnessRenderer(
            Destination(
                "x", tmp_path, profile, scope="project", options={"variant": "local"}
            ),
            approximate=profile == "copilot-vscode",
        ).render(item)[0]
        assert output.path == tmp_path / expected
        if profile == "gemini":
            assert tomlkit.parse(output.content.decode())["prompt"] == "Review {{args}}"

    def test_skill_rename_updates_manifest_and_preserves_references(
        self, tmp_path: Path
    ) -> None:
        """Renamed skills retain supporting files and update their identity."""
        item = Customization(
            "new",
            "skills",
            (
                PackageFile(
                    "SKILL.md",
                    b"---\nname: old\ndescription: test\n---\nRead references/x.md",
                ),
                PackageFile("references/x.md", b"reference"),
            ),
            {"name": "old", "description": "test"},
        )
        outputs = HarnessRenderer(Destination("x", tmp_path, "shared")).render(item)
        assert Frontmatter.read(outputs[0].content)[0]["name"] == "new"
        assert outputs[1].path == tmp_path / "skills/new/references/x.md"

    @pytest.mark.parametrize(
        "profile",
        ["claude", "codex", "copilot-cli", "cursor-ide", "gemini"],
        ids=["claude", "codex", "copilot", "cursor", "gemini"],
    )
    def test_native_hook_pass_through(self, tmp_path: Path, profile: str) -> None:
        """Native handlers keep their existing wire contract."""
        event = {"cursor-ide": "stop", "gemini": "AfterAgent"}.get(profile, "Stop")
        handlers: list[JsonValue] = [{"command": "stop"}]
        if profile in ("claude", "codex", "gemini"):
            handlers = [{"hooks": [{"type": "command", "command": "stop"}]}]
        item = Customization(
            "stop",
            "hooks",
            (),
            {"event": event, "handlers": handlers},
            profile,
        )
        output = HarnessRenderer(Destination("x", tmp_path, profile)).render(item)[0]
        expected: JsonValue = (
            {"version": 1, "hooks": {event: handlers}}
            if profile == "copilot-cli"
            else handlers
        )
        assert Json.loads(output.content.decode()) == expected
        assert output.slot == (() if profile == "copilot-cli" else ("hooks", event))

    def test_cross_harness_hooks_block(self, tmp_path: Path) -> None:
        """Similar event names are insufficient evidence of payload compatibility."""
        item = Customization(
            "stop", "hooks", (), {"event": "Stop", "handlers": []}, "claude"
        )
        with pytest.raises(ConversionError, match="payload"):
            HarnessRenderer(Destination("x", tmp_path, "codex")).render(item)

    def test_unknown_profile_and_kind(self, tmp_path: Path) -> None:
        """Unknown harnesses require an explicit custom renderer."""
        with pytest.raises(ConfigurationError, match="profile"):
            ContractRegistry.get("unknown")
        with pytest.raises(ConversionError, match="Unsupported"):
            HarnessRenderer(Destination("x", tmp_path, "claude")).render(
                Customization("x", "unknown", (), {})
            )

    def test_evidence_is_not_native_verification(self) -> None:
        """Fixture verification is not represented as a native runtime test."""
        assert all(
            contract.report()["native_verified"] is False
            for contract in ContractRegistry.CONTRACTS
        )
