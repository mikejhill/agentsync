"""Versioned harness capability contracts and conservative renderers."""

from __future__ import annotations

from dataclasses import dataclass, replace

import tomlkit
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from agentsync.config import Destination
from agentsync.exceptions import ConfigurationError, ConversionError
from agentsync.hooks import HookPolicy
from agentsync.jsonutil import Json, JsonObject
from agentsync.models import Customization, Output
from agentsync.paths import SafePath
from agentsync.readers import Frontmatter


@dataclass(frozen=True, slots=True)
class HarnessContract:
    """Explicit capability, discovery, and evidence descriptor."""

    name: str
    family: str
    documentation: str
    instruction_file: str
    agent_directory: str = "agents"
    prompt_directory: str = "commands"
    config_file: str = "settings.json"
    mcp_key: str = "mcpServers"
    format: str = "json"
    version: int = 1
    verified_date: str = "2026-10-11"
    native_verified: bool = False

    def report(self) -> JsonObject:
        """Describe fixtures separately from native runtime evidence."""
        return {
            "profile": self.name,
            "family": self.family,
            "contract_version": self.version,
            "documentation": self.documentation,
            "documentation_checked": self.verified_date,
            "native_verified": self.native_verified,
            "tested_runtime_versions": [],
            "instructions": self.instruction_file,
            "agents": self.agent_directory,
            "prompts": self.prompt_directory,
            "mcp": self.config_file,
            "reload": "Check harness documentation; AgentSync never restarts a harness",
            "hooks": (
                "Native-profile pass-through only; cross-profile payload"
                " conversion requires an explicit transformation"
            ),
            "fidelity": (
                "Exact basic fields; approximate or unsupported seman"
                "tics diagnosed before writes"
            ),
        }


class ContractRegistry:
    """Built-in harness profiles and independent versioned descriptions."""

    CONTRACTS = (
        HarnessContract(
            "generic", "generic", "https://agentskills.io/specification", "instructions"
        ),
        HarnessContract(
            "shared", "shared", "https://agentskills.io/specification", "AGENTS.md"
        ),
        HarnessContract(
            "claude",
            "claude",
            "https://code.claude.com/docs/en/skills",
            "CLAUDE.md",
            config_file="settings.json",
        ),
        HarnessContract(
            "codex",
            "codex",
            "https://developers.openai.com/codex/config-reference",
            "AGENTS.md",
            prompt_directory="prompts",
            config_file="config.toml",
            mcp_key="mcp_servers",
            format="toml",
        ),
        HarnessContract(
            "codex-desktop",
            "codex",
            "https://developers.openai.com/codex/config-reference",
            "AGENTS.md",
            prompt_directory="prompts",
            config_file="config.toml",
            mcp_key="mcp_servers",
            format="toml",
        ),
        HarnessContract(
            "copilot-cli",
            "copilot",
            (
                "https://docs.github.com/en/copilot/how-tos/copilot-cli/customize"
                "-copilot/add-custom-instructions"
            ),
            "copilot-instructions.md",
            prompt_directory="prompts",
            config_file="mcp-config.json",
        ),
        HarnessContract(
            "copilot-vscode",
            "copilot",
            "https://code.visualstudio.com/docs/agent-customization/overview",
            "copilot-instructions.md",
            prompt_directory="prompts",
            config_file="mcp-config.json",
        ),
        HarnessContract(
            "cursor-ide",
            "cursor",
            "https://cursor.com/docs/context/rules",
            "AGENTS.md",
            config_file="mcp.json",
        ),
        HarnessContract(
            "cursor-cli",
            "cursor",
            "https://cursor.com/docs/cli/using",
            "AGENTS.md",
            config_file="mcp.json",
        ),
        HarnessContract(
            "gemini",
            "gemini",
            "https://geminicli.com/docs/reference/configuration/",
            "GEMINI.md",
            config_file="settings.json",
        ),
        HarnessContract(
            "opencode",
            "opencode",
            "https://opencode.ai/docs/config/",
            "AGENTS.md",
            config_file="opencode.jsonc",
            mcp_key="mcp",
            format="jsonc",
        ),
    )

    @classmethod
    def get(cls, name: str) -> HarnessContract:
        """Resolve known profiles without guessing unfamiliar schemas."""
        contract = next((item for item in cls.CONTRACTS if item.name == name), None)
        if contract is None:
            raise ConfigurationError(f"Unknown harness profile {name}")
        return contract


class HarnessRenderer:
    """Render documented analogues with explicit approximation policy."""

    def __init__(self, destination: Destination, *, approximate: bool = False) -> None:
        self.destination = destination
        self.contract = ContractRegistry.get(destination.profile)
        self._surface_variant()
        self.approximate = approximate
        self.diagnostics: list[str] = []
        self._version_policy()

    def _surface_variant(self) -> None:
        """Select explicitly different VS Code Local and Agent Host schemas."""
        if self.contract.name != "copilot-vscode":
            return
        variant = Json.string(
            (self.destination.options or {}).get("variant", "agent-host")
        )
        if variant not in ("agent-host", "local"):
            raise ConfigurationError("VS Code variant must be agent-host or local")
        if variant == "local":
            self.contract = replace(
                self.contract, config_file="mcp.json", mcp_key="servers", format="jsonc"
            )

    def _version_policy(self) -> None:
        """Require an explicit runtime version for constrained profiles."""
        if self.destination.version is None:
            return
        runtime = (self.destination.options or {}).get("runtime_version")
        if runtime is None:
            raise ConfigurationError(
                "A version constraint requires options.runtime_version; "
                "automatic native version discovery is unavailable"
            )
        try:
            permitted = SpecifierSet(self.destination.version)
            actual = Version(Json.string(runtime))
        except (InvalidSpecifier, InvalidVersion) as error:
            raise ConfigurationError("Invalid harness version policy") from error
        if actual not in permitted:
            raise ConversionError("Configured harness version fails its constraint")

    def render(self, item: Customization) -> tuple[Output, ...]:
        """Render a complete customization package."""
        self.diagnostics.clear()
        SafePath.relative(item.name)
        if self.contract.name == "generic":
            return self._package(item, f"{item.kind}/{item.name}")
        handler = {
            "skills": self._skill,
            "instructions": self._instruction,
            "agents": self._agent,
            "prompts": self._prompt,
            "mcp": self._mcp,
            "hooks": self._hook,
        }.get(item.kind)
        if handler is None:
            raise ConversionError(
                f"Unsupported kind {item.kind} in {self.contract.name}"
            )
        outputs = handler(item)
        if item.kind == "skills" or len(item.files) == 1:
            return outputs
        primary = outputs[0]
        supporting = tuple(
            replace(
                primary,
                path=SafePath.child(primary.path.parent, file.path),
                content=file.content,
                slot=(),
                format="file",
                mode=file.mode,
            )
            for file in item.files[1:]
        )
        return (*outputs, *supporting)

    def _output(
        self,
        item: Customization,
        path: str,
        content: bytes,
        *,
        slot: tuple[str, ...] = (),
        format_name: str = "file",
    ) -> Output:
        """Attach provenance to a contained proposed output."""
        return Output(
            SafePath.child(self.destination.location, path),
            content,
            self.destination.name,
            (
                f"{item.source}:{item.kind}/{item.name}",
                f"contract:{self.contract.name}@{self.contract.version}",
            ),
            slot,
            format_name,
        )

    def _package(self, item: Customization, prefix: str) -> tuple[Output, ...]:
        """Preserve package content and relative supporting references."""
        return tuple(
            Output(
                SafePath.child(self.destination.location, f"{prefix}/{file.path}"),
                file.content,
                self.destination.name,
                (
                    f"{item.source}:{item.kind}/{item.name}",
                    f"contract:{self.contract.name}@{self.contract.version}",
                ),
                mode=file.mode,
            )
            for file in item.files
        )

    def _loss(self, reason: str) -> None:
        """Block approximations unless explicitly allowed."""
        if not self.approximate:
            raise ConversionError(
                "Approximate conversion requires allow_approximate: " + reason
            )
        self.diagnostics.append("Approximate: " + reason)

    def _skill(self, item: Customization) -> tuple[Output, ...]:
        """Export standard skill packages and update names/metadata."""
        if self.contract.family == "codex":
            raise ConversionError(
                "Codex skills belong in a shared .agents destination; route s"
                "kills there explicitly"
            )
        unknown = set(item.metadata) - {
            "name",
            "description",
            "license",
            "compatibility",
            "metadata",
            "allowed-tools",
        }
        if unknown and item.style not in (self.contract.name, self.contract.family):
            self._loss(
                "Skill activation fields may differ: " + ", ".join(sorted(unknown))
            )
        outputs = list(self._package(item, f"skills/{item.name}"))
        for index, file in enumerate(item.files):
            if file.path == "SKILL.md":
                _, body = Frontmatter.read(file.content)
                outputs[index] = self._output(
                    item,
                    f"skills/{item.name}/SKILL.md",
                    Frontmatter.write(item.metadata | {"name": item.name}, body),
                )
        return tuple(outputs)

    def _instruction(self, item: Customization) -> tuple[Output, ...]:
        """Translate scoped rules without widening their scope silently."""
        if self.contract.family == "shared" and self.destination.scope == "user":
            raise ConversionError(
                "Shared user .agents discovers skills, not global instructions; "
                "route instructions to each harness's native configuration root"
            )
        if self.contract.family == "cursor" and self.destination.scope == "user":
            raise ConversionError(
                "Cursor global user rules are managed by its UI; "
                "configure a project destination for filesystem instructions"
            )
        _, body = Frontmatter.read(item.files[0].content)
        pattern = item.metadata.get(
            "applyTo", item.metadata.get("paths", item.metadata.get("globs"))
        )
        self._instruction_metadata(item, pattern)
        if pattern is None:
            output = self._output(
                item,
                self.contract.instruction_file,
                body.encode(),
                slot=(item.name,),
                format_name="markdown",
            )
            if (
                self.contract.family == "cursor"
                and self.destination.location.name == ".cursor"
            ):
                output = replace(
                    output,
                    path=SafePath.child(self.destination.location.parent, "AGENTS.md"),
                )
            return (output,)
        if self.contract.family not in ("claude", "copilot", "cursor"):
            self._loss(
                f"{self.contract.name} has no exact path-scoped instruction analogue"
            )
            return (
                self._output(
                    item,
                    self.contract.instruction_file,
                    (
                        f"Apply this guidance only to paths matching {pattern}:\n\n"
                        + body
                    ).encode(),
                    slot=(item.name,),
                    format_name="markdown",
                ),
            )
        metadata, directory, extension = self._scoped_instruction(pattern)
        return (
            self._output(
                item,
                f"{directory}/{item.name}{extension}",
                Frontmatter.write(metadata, body),
            ),
        )

    def _instruction_metadata(self, item: Customization, pattern: object) -> None:
        """Diagnose native activation restrictions the rule writer cannot preserve."""
        unknown = set(item.metadata) - {
            "name",
            "description",
            "applyTo",
            "paths",
            "globs",
        }
        if unknown:
            self._loss(
                "Instruction activation fields require mapping: "
                + ", ".join(sorted(unknown))
            )
        if (
            pattern is None
            and bool(item.metadata.get("description"))
            and item.style
            in (
                "copilot",
                "copilot-cli",
                "copilot-vscode",
                "cursor",
                "cursor-ide",
                "cursor-cli",
            )
        ):
            self._loss(
                "Task-relevant native instructions would become always-on guidance"
            )

    def _scoped_instruction(self, pattern: object) -> tuple[JsonObject, str, str]:
        """Map path conditions between documented instruction formats."""
        value = Json.value(pattern)
        if self.contract.family == "claude":
            paths = Json.value(
                value
                if isinstance(value, list)
                else [part.strip() for part in Json.string(value).split(",")]
            )
            return {"paths": paths}, "rules", ".md"
        if self.contract.family == "copilot":
            return (
                {
                    "applyTo": ",".join(Json.strings(value))
                    if isinstance(value, list)
                    else value
                },
                "instructions",
                ".instructions.md",
            )
        if self.contract.family == "cursor":
            return {"globs": value, "alwaysApply": False}, "rules", ".mdc"
        self._loss(
            f"{self.contract.name} has no exact path-scoped instruction analogue"
        )
        return {"description": f"Apply only to {value}"}, "instructions", ".md"

    def _agent(self, item: Customization) -> tuple[Output, ...]:
        """Convert basic agent semantics and diagnose native restrictions."""
        metadata, body = Frontmatter.read(item.files[0].content)
        metadata |= item.metadata
        if not bool(metadata.get("description")):
            raise ConversionError(f"Agent {item.name} requires description")
        family = self.contract.family
        if family in ("generic", "shared", "gemini"):
            raise ConversionError(
                f"Agent conversion unsupported for {self.contract.name}"
            )
        native = item.style in (self.contract.name, family)
        supported = {"name", "description", "model"}
        if not native and item.style != "portable" and "model" in metadata:
            self._loss("Native model identifiers require explicit target mapping")
            metadata.pop("model")
        if not native and set(metadata) - supported:
            self._loss("Agent tools/permissions/native fields require explicit mapping")
            metadata = {
                key: value for key, value in metadata.items() if key in supported
            }
        if family == "codex":
            content = tomlkit.dumps(
                metadata | {"name": item.name, "developer_instructions": body}
            ).encode()
            return (self._output(item, f"agents/{item.name}.toml", content),)
        metadata["name"] = item.name
        if family == "opencode":
            metadata.pop("name", None)
            metadata["mode"] = "subagent"
        extension = ".agent.md" if self.contract.name == "copilot-vscode" else ".md"
        return (
            self._output(
                item,
                f"{self.contract.agent_directory}/{item.name}{extension}",
                Frontmatter.write(metadata, body),
            ),
        )

    def _prompt(self, item: Customization) -> tuple[Output, ...]:
        """Convert invocable prompts while diagnosing activation differences."""
        metadata, body = Frontmatter.read(item.files[0].content)
        metadata |= item.metadata
        family = self.contract.family
        if (
            self.contract.name == "copilot-vscode"
            and self.contract.mcp_key != "servers"
        ):
            raise ConversionError(
                "Agent Host does not load prompt files; use a prompt-to-skill "
                "transformation or options.variant=local for Local sessions"
            )
        if family in ("shared", "copilot") and self.contract.name != "copilot-vscode":
            raise ConversionError(
                f"Standalone prompt discovery unsupported for {self.contract.name}"
            )
        if item.style not in ("portable", family, self.contract.name) and metadata:
            self._loss("Prompt invocation fields differ")
        if family == "gemini":
            content = tomlkit.dumps(
                {
                    "description": metadata.get("description", item.name),
                    "prompt": body.replace("$ARGUMENTS", "{{args}}"),
                }
            ).encode()
            return (self._output(item, f"commands/{item.name}.toml", content),)
        extension = ".prompt.md" if self.contract.name == "copilot-vscode" else ".md"
        if self.contract.name == "copilot-vscode" and "$ARGUMENTS" in body:
            self._loss("Prompt arguments become interactive input guidance")
            body = body.replace("$ARGUMENTS", "${input:args}")
        if self.contract.name == "copilot-vscode" and self.destination.scope == "user":
            raise ConversionError(
                "VS Code user prompts require a profile-specific native directory; "
                "configure a project .github destination or a custom renderer"
            )
        return (
            self._output(
                item,
                f"{self.contract.prompt_directory}/{item.name}{extension}",
                Frontmatter.write(metadata, body),
            ),
        )

    def _mcp(self, item: Customization) -> tuple[Output, ...]:
        """Project named MCP declarations into owned configuration slots."""
        if self.contract.family == "shared":
            raise ConversionError("Shared .agents has no native MCP configuration")
        data = self._mcp_metadata(item)
        self._validate_mcp(item, data)
        if not bool(data.get("command")) and not bool(data.get("url")):
            raise ConversionError("MCP server requires command or url")
        return self._mcp_output(item, data)

    def _validate_mcp(self, item: Customization, data: JsonObject) -> None:
        """Validate transports and prevent silently enabled or invalid declarations."""
        self._validate_mcp_fields(data)
        if item.style in (self.contract.name, self.contract.family):
            return
        if data.get("enabled") is False:
            raise ConversionError(
                "Disabled native MCP servers require explicit target mapping"
            )
        common = {
            "command",
            "args",
            "env",
            "environment",
            "url",
            "type",
            "headers",
            "http_headers",
        }
        unknown = set(data) - common
        if unknown:
            self._loss(
                "MCP native fields require mapping: " + ", ".join(sorted(unknown))
            )
            for field in unknown:
                data.pop(field)

    @staticmethod
    def _validate_mcp_fields(data: JsonObject) -> None:
        """Validate shared scalar, argument, and environment field types."""
        for field in ("command", "url"):
            if field in data:
                value = data[field]
                if field == "command" and isinstance(value, list):
                    Json.strings(value)
                else:
                    Json.string(value)
        if "command" in data and "url" in data:
            raise ConversionError("MCP declaration must choose command or url")
        if "args" in data:
            Json.strings(data["args"])
        for field in ("env", "environment", "headers", "http_headers"):
            if field in data:
                for value in Json.object(data[field]).values():
                    Json.string(value)

    def _mcp_metadata(self, item: Customization) -> JsonObject:
        """Normalize supported native transports and translate target schema fields."""
        data = self._native_mcp(item)
        family = self.contract.family
        if family == "opencode":
            command = data.get("command")
            if bool(command):
                data["type"] = "local"
                data["command"] = Json.value(
                    [Json.string(command), *Json.strings(data.pop("args", []))]
                )
            else:
                data["type"] = "remote"
            if "env" in data:
                data["environment"] = data.pop("env")
        elif family != "codex" and bool(data.get("url")):
            data.setdefault("type", "http")
        if family == "codex" and "headers" in data:
            data["http_headers"] = data.pop("headers")
        if family == "codex":
            data.pop("type", None)
        return data

    @staticmethod
    def _native_mcp(item: Customization) -> JsonObject:
        """Interpret native transport fields without resolving credential references."""
        data = dict(item.metadata)
        if item.style == "opencode":
            command = data.get("command")
            if isinstance(command, list):
                parts = Json.strings(command)
                if not parts:
                    raise ConversionError("OpenCode command array is empty")
                data["command"] = parts[0]
                data["args"] = Json.value(list(parts[1:]))
            data.pop("type", None)
            if "environment" in data:
                data["env"] = data.pop("environment")
        if item.style in ("codex", "codex-desktop") and "http_headers" in data:
            data["headers"] = data.pop("http_headers")
        return data

    def _mcp_output(self, item: Customization, data: JsonObject) -> tuple[Output, ...]:
        """Select native or explicitly configured MCP documents."""
        family = self.contract.family
        path = self.contract.config_file
        if (
            self.contract.name == "copilot-vscode"
            and self.destination.scope == "project"
        ):
            path = "mcp.json" if self.contract.mcp_key == "servers" else ".mcp.json"
        if family == "claude":
            path = ".mcp.json"
            if self.destination.scope == "user":
                output = self._output(
                    item,
                    "mcp.json",
                    Json.dumps(data).encode(),
                    slot=(self.contract.mcp_key, item.name),
                    format_name="json",
                )
                override = (self.destination.options or {}).get("mcp_file")
                native = (
                    SafePath.configured(
                        Json.string(override), self.destination.location
                    )
                    if override is not None
                    else self.destination.location.parent / ".claude.json"
                )
                return (
                    replace(output, path=SafePath.child(native.parent, native.name)),
                )
        output = self._output(
            item,
            path,
            Json.dumps(data).encode(),
            slot=(self.contract.mcp_key, item.name),
            format_name=self.contract.format,
        )
        override = (self.destination.options or {}).get("mcp_file")
        if override is not None:
            native = SafePath.configured(
                Json.string(override), self.destination.location
            )
            output = replace(output, path=SafePath.child(native.parent, native.name))
        elif family == "claude" and self.destination.location.name == ".claude":
            output = replace(
                output,
                path=SafePath.child(self.destination.location.parent, ".mcp.json"),
            )
        elif (
            self.contract.name == "copilot-vscode"
            and self.destination.scope == "project"
            and self.destination.location.name == ".github"
        ):
            root = self.destination.location.parent
            native = (
                root / ".vscode/mcp.json"
                if self.contract.mcp_key == "servers"
                else root / ".mcp.json"
            )
            output = replace(output, path=SafePath.child(native.parent, native.name))
        return (output,)

    def _hook(self, item: Customization) -> tuple[Output, ...]:
        """Preserve native hook payload contracts without guessed rewrites."""
        if item.style not in (self.contract.name, self.contract.family):
            raise ConversionError(
                "Hook payload/decision conversion requires an explicit native"
                "-style transformation"
            )
        if self.contract.family in ("shared", "opencode"):
            raise ConversionError("This target requires a plugin hook adapter")
        data = item.metadata
        event = Json.string(data.get("event"))
        handlers = Json.array(data.get("handlers"))
        HookPolicy.validate(self.contract.family, event, handlers)
        path = (
            "settings.json"
            if self.contract.family in ("claude", "gemini")
            else "hooks.json"
        )
        if self.contract.family == "copilot":
            path = f"hooks/agentsync-{item.name}.json"
            return (
                self._output(
                    item,
                    path,
                    Json.dumps({"version": 1, "hooks": {event: handlers}}).encode(),
                ),
            )
        outputs = (
            self._output(
                item,
                path,
                Json.dumps(handlers).encode(),
                slot=("hooks", event),
                format_name="json",
            ),
        )
        if self.contract.family == "cursor":
            return (
                *outputs,
                self._output(item, path, b"1", slot=("version",), format_name="json"),
            )
        return outputs
