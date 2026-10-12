"""Native hook structural contracts; payload semantics remain harness-specific."""

from __future__ import annotations

from skillsinc.exceptions import ConversionError
from skillsinc.jsonutil import Json, JsonValue


class HookPolicy:
    """Validate event discovery and handler shapes without executing hooks."""

    @staticmethod
    def validate(family: str, event: str, handlers: list[JsonValue]) -> None:
        """Reject unknown events and malformed native command declarations."""
        events = {
            "claude": (
                "SessionStart",
                "SessionEnd",
                "UserPromptSubmit",
                "PreToolUse",
                "PostToolUse",
                "PostToolUseFailure",
                "PermissionRequest",
                "Notification",
                "Stop",
                "SubagentStart",
                "SubagentStop",
                "PreCompact",
                "PostCompact",
                "Setup",
                "WorktreeCreate",
                "WorktreeRemove",
                "TaskCompleted",
                "TeammateIdle",
            ),
            "codex": (
                "SessionStart",
                "UserPromptSubmit",
                "PreToolUse",
                "PostToolUse",
                "Stop",
                "SubagentStart",
                "SubagentStop",
                "PreCompact",
                "SessionEnd",
                "Notification",
                "PermissionRequest",
            ),
            "gemini": (
                "SessionStart",
                "SessionEnd",
                "BeforeAgent",
                "AfterAgent",
                "BeforeModel",
                "AfterModel",
                "BeforeToolSelection",
                "BeforeTool",
                "AfterTool",
                "PreCompress",
                "Notification",
            ),
            "cursor": (
                "sessionStart",
                "sessionEnd",
                "preToolUse",
                "postToolUse",
                "postToolUseFailure",
                "subagentStart",
                "subagentStop",
                "beforeShellExecution",
                "afterShellExecution",
                "beforeMCPExecution",
                "afterMCPExecution",
                "beforeReadFile",
                "afterFileEdit",
                "beforeSubmitPrompt",
                "preCompact",
                "stop",
                "afterAgentResponse",
                "afterAgentThought",
                "beforeTabFileRead",
                "afterTabFileEdit",
                "workspaceOpen",
            ),
            "copilot": (
                "sessionStart",
                "sessionEnd",
                "userPromptSubmitted",
                "preToolUse",
                "postToolUse",
                "postToolUseFailure",
                "agentStop",
                "subagentStart",
                "subagentStop",
                "preCompact",
                "permissionRequest",
                "notification",
                "SessionStart",
                "SessionEnd",
                "UserPromptSubmit",
                "PreToolUse",
                "PostToolUse",
                "Stop",
                "SubagentStart",
                "SubagentStop",
                "PreCompact",
                "PermissionRequest",
                "Notification",
            ),
        }
        if event not in events.get(family, ()):
            raise ConversionError(f"Unknown {family} hook event {event}")
        for handler in handlers:
            entry = Json.object(handler)
            nested = entry.get("hooks")
            commands = Json.array(nested) if nested is not None else [entry]
            if family in ("claude", "codex", "gemini") and nested is None:
                raise ConversionError(
                    "This native hook contract requires a hooks group"
                )
            for command in commands:
                HookPolicy._handler(family, Json.object(command))

    @staticmethod
    def _handler(family: str, entry: dict[str, JsonValue]) -> None:
        """Check executable/prompt/HTTP payload declarations by native family."""
        kind = Json.string(entry.get("type", "command"))
        keys = (
            ("bash", "powershell", "command", "exec")
            if family == "copilot"
            else ("command",)
        )
        if kind == "prompt":
            keys = ("prompt",) if family != "cursor" else ("command",)
        elif kind == "http":
            keys = ("url",)
        elif kind != "command":
            raise ConversionError(f"Unsupported native hook handler type {kind}")
        if not any(
            isinstance(entry.get(key), str) and bool(entry[key]) for key in keys
        ):
            raise ConversionError("Hook handler has no native executable/prompt/url")
