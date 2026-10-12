"""Per-user login startup integration without altering user customizations."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from agentsync.exceptions import AppError
from agentsync.jsonutil import Json, JsonObject
from agentsync.paths import XdgPaths


@dataclass(frozen=True, slots=True)
class ServiceDefinition:
    """Generated native service file and manager operations."""

    path: Path
    content: bytes
    install: tuple[tuple[str, ...], ...]
    start: tuple[str, ...]
    stop: tuple[str, ...]
    uninstall: tuple[tuple[str, ...], ...]
    status: tuple[str, ...]


class ServiceManager:
    """Explicitly installed platform login startup for foreground watch."""

    def __init__(
        self,
        paths: XdgPaths,
        config: Path,
        *,
        platform: str | None = None,
        executable: Path | None = None,
    ) -> None:
        self.paths = paths
        self.config = config.absolute()
        self.platform = platform or sys.platform
        self.executable = executable or Path(sys.executable)

    def definition(self) -> ServiceDefinition:
        """Generate native configuration without installing it."""
        argv = (
            str(self.executable),
            "-m",
            "agentsync.service_runner",
            str(self.paths.data / "startup/environment.json"),
            "watch",
            "--config-file",
            str(self.config),
            "--background-log",
            str(self.paths.state / "watch.log"),
        )
        if self.platform == "win32":
            return self._windows(argv)
        if self.platform == "darwin":
            return self._macos(argv)
        return self._linux(argv)

    def execute(self, action: str) -> JsonObject:
        """Manage only this application's startup definition."""
        definition = self.definition()
        if action == "status":
            return {
                "version": 1,
                "installed": definition.path.exists(),
                "path": str(definition.path),
                "manager": self._run(definition.status, check=False)
                if definition.path.exists() and definition.status
                else "not-installed",
            }
        if action == "install":
            self._install(definition)
        elif action == "uninstall":
            if definition.path.exists():
                for command in definition.uninstall:
                    self._run(command)
                definition.path.unlink(missing_ok=True)
        elif action in ("start", "stop"):
            if not definition.path.exists():
                raise AppError("Startup integration not installed; run service install")
            command = definition.start if action == "start" else definition.stop
            if not command:
                raise AppError(
                    "Desktop autostart starts on next login; use foreground w"
                    "atch for immediate execution"
                )
            self._run(command)
        else:
            raise AppError(f"Unknown service action {action}")
        return {
            "version": 1,
            "action": action,
            "path": str(definition.path),
            "ok": True,
        }

    def _install(self, definition: ServiceDefinition) -> None:
        """Preserve XDG roots and replace only this application's native service."""
        self.paths.state.mkdir(parents=True, exist_ok=True)
        environment = self.paths.data / "startup/environment.json"
        environment.parent.mkdir(parents=True, exist_ok=True)
        environment.write_text(
            Json.dumps(
                {
                    "XDG_CONFIG_HOME": str(self.paths.config.parent),
                    "XDG_DATA_HOME": str(self.paths.data.parent),
                    "XDG_STATE_HOME": str(self.paths.state.parent),
                    "XDG_CACHE_HOME": str(self.paths.cache.parent),
                }
            ),
            encoding="utf-8",
        )
        definition.path.parent.mkdir(parents=True, exist_ok=True)
        if self.platform == "darwin" and definition.path.exists():
            for command in definition.uninstall:
                self._run(command, check=False)
        definition.path.write_bytes(definition.content)
        for command in definition.install:
            self._run(command)

    def _windows(self, argv: tuple[str, ...]) -> ServiceDefinition:
        """Create a hidden per-user Task Scheduler definition."""
        executable = self.executable.with_name("pythonw.exe")
        command = str(executable if executable.exists() else self.executable)
        arguments = subprocess.list2cmdline(list(argv[1:]))
        xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
<Triggers><LogonTrigger><Enabled>true</Enabled></LogonTrigger></Triggers>
<Principals><Principal id="Author">
<LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel>
</Principal></Principals>
<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><Hidden>true</Hidden></Settings>
<Actions Context="Author"><Exec><Command>{escape(command)}</Command>
<Arguments>{escape(arguments)}</Arguments></Exec></Actions></Task>"""
        path = self.paths.data / "startup" / "task.xml"
        return ServiceDefinition(
            path,
            xml.encode("utf-16"),
            (("schtasks", "/Create", "/TN", "AgentSync", "/XML", str(path), "/F"),),
            ("schtasks", "/Run", "/TN", "AgentSync"),
            ("schtasks", "/End", "/TN", "AgentSync"),
            (("schtasks", "/Delete", "/TN", "AgentSync", "/F"),),
            ("schtasks", "/Query", "/TN", "AgentSync"),
        )

    def _macos(self, argv: tuple[str, ...]) -> ServiceDefinition:
        """Create a user LaunchAgent with restart and log handling."""
        path = Path.home() / "Library/LaunchAgents/dev.agentsync.watch.plist"
        getuid = getattr(os, "getuid", None)
        domain = f"gui/{getuid() if getuid is not None else 0}"
        payload = {
            "Label": "dev.agentsync.watch",
            "ProgramArguments": list(argv),
            "RunAtLoad": True,
            "KeepAlive": True,
            "StandardErrorPath": str(self.paths.state / "service.log"),
        }
        return ServiceDefinition(
            path,
            plistlib.dumps(payload),
            (("launchctl", "bootstrap", domain, str(path)),),
            ("launchctl", "kickstart", f"{domain}/dev.agentsync.watch"),
            ("launchctl", "kill", "SIGTERM", f"{domain}/dev.agentsync.watch"),
            (("launchctl", "bootout", domain, str(path)),),
            ("launchctl", "print", f"{domain}/dev.agentsync.watch"),
        )

    def _linux(self, argv: tuple[str, ...]) -> ServiceDefinition:
        """Generate systemd user startup or XDG desktop autostart."""
        config_root = self.paths.config.parent
        systemd = self._systemd_available()
        command = " ".join(
            '"'
            + part.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("%", "%%")
            .replace("$", "$$" if systemd else "\\$")
            .replace("`", "\\`")
            + '"'
            for part in argv
        )
        if systemd:
            path = config_root / "systemd/user/agentsync.service"
            content = (
                "[Unit]\nDescription=AgentSync customization distribution\n"
                f"[Service]\nExecStart={command}\nRestart=on-failure\n"
                "[Install]\nWantedBy=default.target\n"
            ).encode()
            return ServiceDefinition(
                path,
                content,
                (
                    ("systemctl", "--user", "daemon-reload"),
                    ("systemctl", "--user", "enable", "agentsync.service"),
                ),
                ("systemctl", "--user", "start", "agentsync.service"),
                ("systemctl", "--user", "stop", "agentsync.service"),
                (("systemctl", "--user", "disable", "--now", "agentsync.service"),),
                ("systemctl", "--user", "is-active", "agentsync.service"),
            )
        path = config_root / "autostart/agentsync.desktop"
        return ServiceDefinition(
            path,
            (
                "[Desktop Entry]\nType=Application\nName=AgentSync\n"
                f"Exec={command}\nTerminal=false\n"
            ).encode(),
            (),
            (),
            (),
            (),
            (),
        )

    @staticmethod
    def _systemd_available() -> bool:
        """Probe the user manager; an installed binary alone does not establish it."""
        executable = shutil.which("systemctl")
        if executable is None:
            return False
        try:
            result = subprocess.run(  # noqa: S603 - resolved native manager, no shell
                [executable, "--user", "show-environment"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0

    @staticmethod
    def _run(argv: tuple[str, ...], *, check: bool = True) -> str:
        """Execute a native manager without a shell or credentials."""
        try:
            result = subprocess.run(  # noqa: S603 - explicit trusted argv, no shell
                argv, capture_output=True, text=True, check=check, timeout=30
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise AppError("Native startup manager failed") from error
        return result.stdout.strip()
