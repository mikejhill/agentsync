"""Argument parsing into immutable command settings."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from agentsync import __version__


@dataclass(frozen=True, slots=True)
class Command:
    """Typed CLI boundary."""

    name: str
    config: Path | None
    targets: tuple[str, ...]
    json: bool
    verbose: bool
    action: str = ""
    query: str = ""
    once: bool = False
    background_log: Path | None = None


class CommandLine:
    """Discoverable argparse interface for humans and schedulers."""

    def parse(self, argv: Sequence[str] | None = None) -> Command:
        """Convert an argparse namespace immediately into typed values."""
        parser = argparse.ArgumentParser(
            prog="agentsync",
            description="Distribute agent customizations from user-owned sources.",
        )
        parser.add_argument(
            "--version", action="version", version=f"AgentSync {__version__}"
        )
        common = argparse.ArgumentParser(add_help=False)
        common.add_argument(
            "--config-file",
            type=Path,
            help="Use explicit configuration; disable default bootstrap",
        )
        common.add_argument(
            "--target",
            action="append",
            default=[],
            help="Select a destination by name (repeatable)",
        )
        common.add_argument(
            "--json", action="store_true", help="Emit versioned JSON report"
        )
        common.add_argument(
            "-v", "--verbose", action="store_true", help="Enable diagnostic logging"
        )
        subparsers = parser.add_subparsers(dest="command", required=True)
        for name in ("init", "validate", "plan", "sync", "status", "adopt"):
            subparsers.add_parser(name, parents=[common])
        explain = subparsers.add_parser("explain", parents=[common])
        explain.add_argument(
            "query",
            nargs="?",
            default="",
            help="Customization, path, or provenance fragment",
        )
        watch = subparsers.add_parser("watch", parents=[common])
        watch.add_argument(
            "--once", action="store_true", help="Perform initial sync and exit"
        )
        watch.add_argument(
            "--background-log", type=Path, help="Log background diagnostics to a file"
        )
        service = subparsers.add_parser("service", parents=[common])
        service.add_argument(
            "action", choices=("install", "uninstall", "start", "stop", "status")
        )
        contracts = subparsers.add_parser("contracts", parents=[common])
        contracts.add_argument("action", choices=("list", "show"))
        contracts.add_argument("query", nargs="?", default="")
        namespace = parser.parse_args(argv)
        config = namespace.config_file
        background_log = getattr(namespace, "background_log", None)
        return Command(
            str(namespace.command),
            Path(config) if config is not None else None,
            tuple(str(value) for value in namespace.target),
            bool(namespace.json),
            bool(namespace.verbose),
            str(getattr(namespace, "action", "")),
            str(getattr(namespace, "query", "")),
            bool(getattr(namespace, "once", False)),
            Path(background_log) if background_log else None,
        )
