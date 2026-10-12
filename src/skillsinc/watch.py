"""Event-driven reconciliation with periodic missed-event recovery."""

from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path
from threading import Event
from typing import override

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from skillsinc.config import Configuration, Settings
from skillsinc.engine import Engine
from skillsinc.exceptions import AppError
from skillsinc.jsonutil import JsonObject
from skillsinc.paths import XdgPaths

logger = logging.getLogger(__name__)


class ChangeHandler(FileSystemEventHandler):
    """Coalesce filesystem events into one reconciliation signal."""

    def __init__(self, changed: Event, ignored: tuple[Path, ...] = ()) -> None:
        self.changed = changed
        self.ignored = tuple(root.resolve() for root in ignored)

    @override
    def on_any_event(self, event: FileSystemEvent) -> None:
        """Ignore read-only events to prevent feedback from scans."""
        path = Path(os.fsdecode(event.src_path)).absolute()
        if path.name.startswith(".skillsinc-") or any(
            path.is_relative_to(root) for root in self.ignored
        ):
            return
        if event.event_type not in ("opened", "closed_no_write"):
            self.changed.set()


class WatchCoordinator:
    """Run the same engine used by manual sync with configurable timers."""

    def __init__(
        self,
        paths: XdgPaths,
        file: Path | None = None,
        targets: tuple[str, ...] = (),
        engine: Engine | None = None,
    ) -> None:
        self.paths = paths
        self.file = file
        self.targets = targets
        self.engine = engine or Engine(paths)
        self.changed = Event()
        self.stop = Event()
        self.settings: Settings | None = None
        self.last_run = float("-inf")
        self.last_remote = float("-inf")
        self.last_event: float | None = None
        self.failures = 0

    def tick(self, now: float, *, event: bool = False) -> JsonObject | None:
        """Advance deterministic debounce, retry, and polling state."""
        if event:
            self.last_event = now
        if self.settings is None:
            self.settings = Configuration(self.paths).load(self.file, bootstrap=True)
        settings = self.settings
        due = now - self.last_run >= min(settings.poll, settings.verify)
        debounced = (
            self.last_event is not None and now - self.last_event >= settings.debounce
        )
        if not due and not debounced:
            return None
        if self.failures and now - self.last_run < min(60, 2**self.failures):
            return None
        try:
            self.settings = Configuration(self.paths).load(self.file)
        except (AppError, OSError, UnicodeError) as error:
            logger.warning(
                "Invalid config edit; retaining last valid policy: %s", error
            )
        fetch = now - self.last_remote >= self.settings.remote_poll
        report = self.engine.run(self.settings, self.targets, apply=True, fetch=fetch)
        self.last_run = now
        self.last_event = None
        if fetch:
            self.last_remote = now
        self.failures = 0 if bool(report.get("ok")) else min(self.failures + 1, 6)
        if self.failures:
            logger.error("Distribution blocked; details: %s", report.get("targets"))
        return report

    def run(self, *, once: bool = False) -> JsonObject:
        """Watch roots, with polling covering missing or newly added roots."""
        initial = self.tick(time.monotonic()) or {"version": 1, "ok": True}
        if once:
            return initial
        observer = Observer()
        handler = ChangeHandler(
            self.changed, (self.paths.state, self.paths.cache, self.paths.data)
        )
        self._subscribe(observer, handler)
        observer.start()
        previous = signal.signal(signal.SIGTERM, self._terminate)
        self._heartbeat("running")
        heartbeat = time.monotonic()
        try:
            while not self.stop.wait(0.1):
                changed = self.changed.is_set()
                self.changed.clear()
                report = self.tick(time.monotonic(), event=changed)
                if report is not None:
                    self._subscribe(observer, handler)
                if time.monotonic() - heartbeat >= 1:
                    self._heartbeat("running")
                    heartbeat = time.monotonic()
        finally:
            observer.stop()
            observer.join(timeout=5)
            signal.signal(signal.SIGTERM, previous)
            self._heartbeat("stopped")
        return self.engine.store.report()

    def _terminate(self, signum: int, frame: object) -> None:
        """Stop gracefully when the native manager sends termination."""
        logger.info("Watcher termination requested: signal=%s frame=%s", signum, frame)
        self.stop.set()

    def _heartbeat(self, state: str) -> None:
        """Expose process identity and wall-time heartbeat to status."""
        self.engine.store.watcher(
            {
                "state": state,
                "pid": os.getpid(),
                "heartbeat": time.time(),
                "cpu_seconds": time.process_time(),
                "config": str(self.settings.file)
                if self.settings is not None
                else None,
            }
        )

    def _subscribe(self, observer: BaseObserver, handler: ChangeHandler) -> None:
        """Rebuild subscriptions after route or source changes."""
        observer.unschedule_all()
        if self.settings is None:
            return
        roots = {self.settings.file.parent}
        roots |= {
            Path(source.location)
            for source in self.settings.sources
            if source.provider == "local"
        }
        roots |= {
            destination.location
            for destination in self.settings.destinations
            if destination.enabled
        }
        for candidate in sorted(roots):
            root = candidate
            while not root.exists() and root != root.parent:
                root = root.parent
            if root.is_dir():
                try:
                    observer.schedule(handler, str(root), recursive=True)
                except OSError as error:
                    logger.warning(
                        "Event subscription failed; polling remains active: %s", error
                    )
