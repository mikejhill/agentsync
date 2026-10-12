"""Application composition and class-based console entry point."""

from __future__ import annotations

import logging
import sqlite3
import sys
from collections.abc import Sequence

from filelock import Timeout

from agentsync.cli import Command, CommandLine
from agentsync.config import Configuration, Settings
from agentsync.contracts import ContractRegistry
from agentsync.engine import Engine
from agentsync.exceptions import AppError, ConfigurationError
from agentsync.jsonutil import Json, JsonObject
from agentsync.loggingutil import StructuredFormatter
from agentsync.paths import XdgPaths
from agentsync.services import ServiceManager
from agentsync.watch import WatchCoordinator

logger = logging.getLogger(__name__)


class Application:
    """Parse arguments, compose services, and report actionable failures."""

    @classmethod
    def main(cls) -> None:
        """Run the installed CLI."""
        sys.exit(cls().run())

    def run(self, argv: Sequence[str] | None = None) -> int:
        """Execute a command with stable scheduler-friendly exit codes."""
        command = CommandLine().parse(argv)
        logging.basicConfig(level=logging.DEBUG if command.verbose else logging.WARNING)
        if command.background_log:
            command.background_log.parent.mkdir(parents=True, exist_ok=True)
            logging.getLogger().addHandler(
                logging.FileHandler(command.background_log, encoding="utf-8")
            )
        for handler in logging.getLogger().handlers:
            handler.setFormatter(StructuredFormatter())
        try:
            result = self._execute(command, XdgPaths.discover())
            self._emit(result, command)
            return 0 if bool(result.get("ok", True)) else 1
        except ConfigurationError as error:
            self._error(error, command)
            return 2
        except (AppError, OSError, sqlite3.Error, Timeout, UnicodeError) as error:
            self._error(error, command)
            return 1
        except KeyboardInterrupt:
            return 130

    @staticmethod
    def _execute(command: Command, paths: XdgPaths) -> JsonObject:
        """Keep dispatch separate from argument parsing and business logic."""
        configuration = Configuration(paths)
        engine = Engine(paths)
        if command.name == "contracts":
            if command.action == "show":
                return ContractRegistry.get(command.query).report()
            return {
                "version": 1,
                "contracts": [
                    contract.report() for contract in ContractRegistry.CONTRACTS
                ],
            }
        if command.name == "init":
            if command.config:
                raise ConfigurationError(
                    "init uses default XDG configuration; "
                    "author explicit config files directly"
                )
            return {"version": 1, "config": str(configuration.initialize()), "ok": True}
        if command.name == "status":
            return Application._status(command, paths, engine)
        if command.name == "watch":
            return WatchCoordinator(paths, command.config, command.targets).run(
                once=command.once
            )
        settings = configuration.load(command.config, bootstrap=command.name == "sync")
        return Application._configured(command, paths, settings, engine)

    @staticmethod
    def _status(command: Command, paths: XdgPaths, engine: Engine) -> JsonObject:
        """Inspect current drift and the selected configuration's last result."""
        if command.config is None and not (paths.config / "config.json").is_file():
            return engine.store.report()
        settings = Configuration(paths).load(command.config)
        result = engine.run(settings, command.targets)
        result["last_run"] = engine.store.report(owner=str(settings.file.resolve()))
        result["watcher"] = engine.store.watcher()
        return result

    @staticmethod
    def _configured(
        command: Command, paths: XdgPaths, settings: Settings, engine: Engine
    ) -> JsonObject:
        """Dispatch commands requiring a valid distribution policy."""
        if command.name == "service":
            return ServiceManager(paths, settings.file).execute(command.action)
        if command.name == "validate":
            plan = engine.planner.build(settings, command.targets, fetch=False)
            return {
                "version": 1,
                "ok": not plan.blocked,
                "blocked": dict(plan.blocked),
                "diagnostics": list(plan.diagnostics),
            }
        result = engine.run(
            settings,
            command.targets,
            apply=command.name in ("sync", "adopt"),
            adopt=command.name == "adopt",
        )
        if command.name == "explain" and command.query:
            result["targets"] = [
                target
                for target in Json.array(result.get("targets"))
                if command.query in Json.dumps(target)
            ]
        return result

    @staticmethod
    def _emit(result: JsonObject, command: Command) -> None:
        """Emit machine JSON or concise human operations."""
        if command.background_log:
            logger.info("Background reconciliation completed")
            return
        if command.json:
            sys.stdout.write(Json.dumps(result))
            return
        if command.name == "explain":
            Application._explain(result)
            return
        if "targets" not in result:
            sys.stdout.write(Json.dumps(result))
            return
        for raw in Json.array(result.get("targets")):
            target = Json.object(raw)
            names = ", ".join(Json.strings(target.get("names")))
            if not bool(target.get("ok")):
                sys.stdout.write(f"BLOCKED {names}: {target.get('error')}\n")
                continue
            operations = Json.array(target.get("operations", []))
            sys.stdout.write(f"OK {names}: {len(operations)} change(s)\n")
            for operation in operations:
                item = Json.object(operation)
                sys.stdout.write(f"  {item.get('action')} {item.get('path')}\n")
        for note in Json.array(result.get("diagnostics", [])):
            sys.stdout.write(f"NOTE {note}\n")

    @staticmethod
    def _explain(result: JsonObject) -> None:
        """Expose source identities and ordered transformations in human output."""
        for raw in Json.array(result.get("targets", [])):
            target = Json.object(raw)
            if not bool(target.get("ok")):
                sys.stdout.write(f"BLOCKED: {target.get('error')}\n")
            for output in Json.array(target.get("outputs", [])):
                record = Json.object(output)
                sys.stdout.write(f"{record.get('path')}\n")
                for origin in Json.strings(record.get("provenance", [])):
                    sys.stdout.write(f"  {origin}\n")

    @staticmethod
    def _error(error: Exception, command: Command) -> None:
        """Expose operational failures without stack traces by default."""
        if command.json and not command.background_log:
            sys.stdout.write(
                Json.dumps({"version": 1, "ok": False, "error": str(error)})
            )
        logger.error("%s", error)


if __name__ == "__main__":
    Application.main()
