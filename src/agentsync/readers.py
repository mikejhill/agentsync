"""Portable packages and native Markdown customization readers."""

from __future__ import annotations

from dataclasses import replace
from pathlib import PurePosixPath

import json5
import tomlkit
import yaml
from tomlkit.exceptions import ParseError

from agentsync.exceptions import ConfigurationError
from agentsync.jsonutil import Json, JsonObject
from agentsync.models import Customization, PackageFile, Snapshot


class Frontmatter:
    """Lossless metadata/body extraction for native Markdown."""

    @staticmethod
    def read(content: bytes) -> tuple[JsonObject, str]:
        """Decode optional YAML frontmatter."""
        text = content.decode("utf-8")
        if not text.startswith("---\n") and not text.startswith("---\r\n"):
            return {}, text
        lines = text.splitlines(keepends=True)
        closing = next(
            (index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"),
            None,
        )
        if closing is None:
            raise ConfigurationError("Unterminated YAML frontmatter")
        try:
            metadata = Json.object(
                Json.value(yaml.safe_load("".join(lines[1:closing])) or {})
            )
        except yaml.YAMLError as error:
            raise ConfigurationError("Invalid YAML frontmatter") from error
        return metadata, "".join(lines[closing + 1 :])

    @staticmethod
    def write(metadata: JsonObject, body: str) -> bytes:
        """Render YAML frontmatter without rewriting body text."""
        if not metadata:
            return body.encode()
        return (
            "---\n"
            + yaml.safe_dump(metadata, sort_keys=True, allow_unicode=True)
            + "---\n"
            + body
        ).encode()


class PackageReader:
    """Interpret kind directories and preserve complete skill packages."""

    KIND_AND_FILE_PARTS = 2

    def read(
        self, snapshot: Snapshot, source: str, style: str
    ) -> tuple[Customization, ...]:
        """Discover customizations using portable or native aliases."""
        try:
            return self._read(snapshot, source, style)
        except (ValueError, ParseError) as error:
            raise ConfigurationError("Invalid native customization document") from error

    def _read(
        self, snapshot: Snapshot, source: str, style: str
    ) -> tuple[Customization, ...]:
        """Read complete packages after source acquisition."""
        groups: dict[tuple[str, str], list[PackageFile]] = {}
        for file in self._native_files(snapshot.files, style):
            parts = PurePosixPath(file.path).parts
            if len(parts) < self.KIND_AND_FILE_PARTS:
                continue
            kind = {
                "commands": "prompts",
                "rules": "instructions",
                "agent": "agents",
                "command": "prompts",
                "skill": "skills",
            }.get(parts[0], parts[0])
            package = kind == "skills" or len(parts) > self.KIND_AND_FILE_PARTS
            name = parts[1] if package else PurePosixPath(parts[1]).stem
            if name.endswith(".instructions"):
                name = name.removesuffix(".instructions")
            if kind == "agents":
                name = name.removesuffix(".agent")
            if kind == "prompts":
                name = name.removesuffix(".prompt")
            relative = "/".join(parts[2:]) if package else parts[1]
            groups.setdefault((kind, name), []).append(replace(file, path=relative))
        return tuple(
            self._item(kind, name, tuple(files), source, style)
            for (kind, name), files in sorted(groups.items())
        )

    @staticmethod
    def _item(
        kind: str, name: str, files: tuple[PackageFile, ...], source: str, style: str
    ) -> Customization:
        """Extract semantics while retaining source bytes."""
        metadata: JsonObject = {}
        manifests = (
            "SKILL.md",
            name + ".md",
            name + ".toml",
            name + ".instructions.md",
        )
        primary = next((file for file in files if file.path in manifests), files[0])
        files = (primary, *(file for file in files if file is not primary))
        if primary.path.endswith(".toml"):
            metadata = Json.object(
                Json.value(tomlkit.parse(primary.content.decode()).unwrap())
            )
            body_key = "developer_instructions" if kind == "agents" else "prompt"
            body = Json.string(metadata.pop(body_key, ""))
            files = (
                replace(
                    primary,
                    path=name + ".md",
                    content=Frontmatter.write(metadata, body),
                ),
                *files[1:],
            )
        elif primary.path.endswith((".md", ".mdc")):
            metadata, _ = Frontmatter.read(primary.content)
        if kind == "skills" and (
            primary.path != "SKILL.md" or not bool(metadata.get("description"))
        ):
            raise ConfigurationError(f"Skill {name} needs SKILL.md and description")
        if kind in ("mcp", "hooks"):
            metadata = Json.object(Json.loads(primary.content.decode()))
        return Customization(
            name, kind, files, metadata, style, source, (f"{source}:{kind}/{name}",)
        )

    @staticmethod
    def _native_files(
        files: tuple[PackageFile, ...], style: str
    ) -> tuple[PackageFile, ...]:
        """Expose native root instruction and settings entries as packages."""
        if style == "portable":
            return files
        result = []
        for file in files:
            if file.path in (
                "AGENTS.md",
                "CLAUDE.md",
                "GEMINI.md",
                "copilot-instructions.md",
            ):
                result.append(replace(file, path="instructions/" + file.path))
            elif file.path in (
                "config.toml",
                "settings.json",
                "mcp.json",
                "mcp-config.json",
                ".mcp.json",
                "hooks.json",
                "opencode.jsonc",
            ):
                parsed = (
                    tomlkit.parse(file.content.decode()).unwrap()
                    if file.path.endswith(".toml")
                    else json5.loads(file.content.decode())
                )
                data = Json.object(Json.value(parsed))
                for name, value in Json.object(
                    data.get(
                        "mcpServers",
                        data.get(
                            "mcp_servers", data.get("mcp", data.get("servers", {}))
                        ),
                    )
                ).items():
                    result.append(
                        PackageFile("mcp/" + name + ".json", Json.dumps(value).encode())
                    )
                for event, handlers in Json.object(data.get("hooks", {})).items():
                    result.append(
                        PackageFile(
                            "hooks/" + event + ".json",
                            Json.dumps({"event": event, "handlers": handlers}).encode(),
                        )
                    )
            else:
                result.append(file)
        return tuple(result)
