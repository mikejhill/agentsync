"""Dedicated performance baselines and targeted safety-decision mutation checks."""

from __future__ import annotations

import argparse
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, replace
from pathlib import Path

from agentsync.config import Configuration, Settings
from agentsync.engine import Engine
from agentsync.jsonutil import Json, JsonObject
from agentsync.paths import XdgPaths
from agentsync.watch import WatchCoordinator


@dataclass(frozen=True, slots=True)
class Corpus:
    """Fixed package/file/byte dimensions shared by approved platform baselines."""

    customizations: int = 5000
    files: int = 20000
    size: int = 250 * 1024 * 1024

    def create(self, root: Path) -> None:
        """Create four-file skill packages totaling the declared byte count."""
        if self.files != self.customizations * 4:
            raise ValueError("Corpus requires four files per customization")
        consumed = 0
        for index in range(self.customizations):
            directory = root / "skills" / f"skill-{index:05}"
            directory.mkdir(parents=True)
            manifest = (
                f"---\nname: skill-{index:05}\ndescription: Benchmark skill\n---\n"
                "Use supporting/file-0.bin.\n"
            ).encode()
            (directory / "SKILL.md").write_bytes(manifest)
            consumed += len(manifest)
        remaining = self.size - consumed
        if remaining < 0:
            raise ValueError("Corpus size is smaller than its manifests")
        count = self.customizations * 3
        per_file, extra = divmod(remaining, count)
        for index in range(count):
            file = (
                root
                / "skills"
                / f"skill-{index // 3:05}"
                / "supporting"
                / f"file-{index % 3}.bin"
            )
            file.parent.mkdir(exist_ok=True)
            file.write_bytes(b"x" * (per_file + int(index < extra)))


class PerformanceGate:
    """Compare repeated measurements against an externally approved baseline."""

    @staticmethod
    def regression(current: list[float], baseline: list[float]) -> bool:
        """Fail >20% mean regressions only when two-sided 95% intervals separate."""
        if len(current) < 5 or len(baseline) < 5:
            raise ValueError("At least five samples are required")
        mean = statistics.mean(current)
        previous = statistics.mean(baseline)
        # Conservative t critical value for five observations; wider than normal.
        margin = 2.776 * statistics.stdev(current) / math.sqrt(len(current))
        old_margin = 2.776 * statistics.stdev(baseline) / math.sqrt(len(baseline))
        return mean > previous * 1.2 and mean - margin > previous + old_margin


class BenchmarkSuite:
    """Measure convergence scenarios in isolated six-target distributions."""

    def __init__(self, root: Path, corpus: Corpus) -> None:
        self.root = root
        self.corpus = corpus

    def run(self, samples: int = 5) -> JsonObject:
        """Measure cold, warm, edit, burst, deletion, shared, and idle behavior."""
        results: dict[str, list[float]] = {}
        for index in range(samples):
            sample = self.root / str(index)
            source = sample / "source"
            self.corpus.create(source)
            settings_file = sample / "config.json"
            data = {
                "version": 1,
                "sources": {"source": {"location": str(source)}},
                "destinations": {
                    f"target-{number}": {
                        "location": str(sample / f"target-{number}"),
                        "enabled": True,
                    }
                    for number in range(6)
                },
                "routes": [
                    {
                        "name": "all",
                        "sources": ["source"],
                        "destinations": [f"target-{number}" for number in range(6)],
                    }
                ],
            }
            paths = XdgPaths(
                *(sample / name for name in ("config", "data", "state", "cache"))
            )
            settings_file.write_text(Json.dumps(data), encoding="utf-8")
            settings = Configuration(paths).load(settings_file)
            engine = Engine(paths)
            self._measure(results, "cold", engine, settings)
            self._measure(results, "warm-noop", engine, settings)
            file = source / "skills/skill-00000/supporting/file-0.bin"
            file.write_bytes(b"changed")
            self._measure(results, "one-file-edit", engine, settings)
            for number in range(min(100, self.corpus.customizations)):
                file = (
                    source / "skills" / f"skill-{number:05}" / "supporting/file-1.bin"
                )
                file.write_bytes(b"burst")
            self._measure(results, "burst", engine, settings)
            for number in range(min(100, self.corpus.customizations)):
                file = (
                    source / "skills" / f"skill-{number:05}" / "supporting/file-2.bin"
                )
                file.unlink()
            self._measure(results, "deletion-batch", engine, settings)
            shared = replace(
                settings,
                destinations=tuple(
                    replace(destination, location=settings.destinations[0].location)
                    for destination in settings.destinations
                ),
            )
            self._measure(results, "shared-targets", engine, shared)
            watcher = WatchCoordinator(paths, settings_file, engine=engine)
            watcher.settings = settings
            watcher.last_run = 0
            watcher.last_remote = 0
            start = time.process_time()
            for _ in range(10000):
                if watcher.tick(0.1) is not None:
                    raise RuntimeError("Idle watcher unexpectedly reconciled")
            results.setdefault("watcher-idle-cpu", []).append(
                time.process_time() - start
            )
            if not sample.resolve().is_relative_to(self.root.resolve()):
                raise RuntimeError("Benchmark cleanup escaped its temporary root")
            shutil.rmtree(sample)
        return Json.record(
            {
                "version": 1,
                "platform": sys.platform,
                "corpus": {
                    "customizations": self.corpus.customizations,
                    "files": self.corpus.files,
                    "bytes": self.corpus.size,
                    "targets": 6,
                },
                "samples": results,
            }
        )

    @staticmethod
    def _measure(
        results: dict[str, list[float]], name: str, engine: Engine, settings: Settings
    ) -> None:
        """Record wall time and require correct distribution before benchmarking it."""
        start = time.perf_counter()
        report = engine.run(settings, apply=True)
        elapsed = time.perf_counter() - start
        if report["ok"] is not True:
            raise RuntimeError(Json.dumps(report))
        results.setdefault(name, []).append(elapsed)


class MutationGate:
    """Kill explicit mutations of deletion, ownership, and fidelity decisions."""

    MUTANTS = (
        (
            "reconcile.py",
            "if key not in context.desired:",
            "if key in context.desired:",
        ),
        (
            "reconcile.py",
            "record is None and existing is not None and not adopt",
            "record is None and existing is not None and adopt",
        ),
        ("contracts.py", "if not self.approximate:", "if self.approximate:"),
    )

    @classmethod
    def run(cls, root: Path) -> JsonObject:
        """Run mutation tests against copied sources; never alter the checkout."""
        results: list[JsonObject] = []
        for module, before, after in cls.MUTANTS:
            with tempfile.TemporaryDirectory(prefix="agentsync-mutation-") as directory:
                clone = Path(directory)
                shutil.copytree(root / "src", clone / "src")
                shutil.copytree(root / "tests", clone / "tests")
                file = clone / "src/agentsync" / module
                text = file.read_text(encoding="utf-8")
                if text.count(before) != 1:
                    raise RuntimeError(f"Mutation anchor changed: {module}: {before}")
                file.write_text(text.replace(before, after), encoding="utf-8")
                environment = dict(os.environ)
                environment["PYTHONPATH"] = str(clone / "src")
                result = subprocess.run(  # noqa: S603 - isolated copies, fixed test argv
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-q",
                        "--import-mode=importlib",
                        "tests/test_engine.py",
                        "tests/test_contracts.py",
                        "tests/test_transactions_sources.py",
                        "--basetemp",
                        str(clone / "tmp"),
                    ],
                    cwd=clone,
                    env=environment,
                    capture_output=True,
                    timeout=180,
                    check=False,
                )
                # Collection/internal errors do not establish a killed mutation.
                killed = result.returncode == 1 and b"failed" in result.stdout
                results.append({"module": module, "decision": before, "killed": killed})
        return Json.record(
            {
                "version": 1,
                "ok": all(result["killed"] is True for result in results),
                "mutants": results,
            }
        )


class QualityApplication:
    """Expose dedicated gates separately from deterministic ordinary tests."""

    @staticmethod
    def main() -> None:
        """Write machine-readable benchmark or mutation evidence."""
        parser = argparse.ArgumentParser()
        parser.add_argument("action", choices=("mutation", "benchmark"))
        parser.add_argument("--output", type=Path, required=True)
        parser.add_argument("--baseline", type=Path)
        parser.add_argument("--quick", action="store_true")
        args = parser.parse_args()
        output = Path(args.output)
        baseline = Path(args.baseline) if args.baseline is not None else None
        if args.action == "mutation":
            report = MutationGate.run(Path.cwd())
            succeeded = report["ok"] is True
        else:
            with tempfile.TemporaryDirectory(
                prefix="agentsync-benchmark-"
            ) as directory:
                corpus = Corpus(5, 20, 1024 * 1024) if bool(args.quick) else Corpus()
                report = BenchmarkSuite(Path(directory), corpus).run()
            succeeded = QualityApplication._compare(report, baseline)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(Json.dumps(report), encoding="utf-8")
        sys.exit(0 if succeeded else 1)

    @staticmethod
    def _compare(report: JsonObject, baseline: Path | None) -> bool:
        """Require a matching approved corpus/platform for performance evidence."""
        if baseline is None:
            report["baseline_status"] = "unapproved; measurements only"
            return False
        previous = Json.object(Json.loads(baseline.read_text(encoding="utf-8")))
        if (
            previous.get("platform") != report["platform"]
            or previous.get("corpus") != report["corpus"]
        ):
            report["baseline_status"] = "platform/corpus mismatch"
            return False
        current = Json.object(report["samples"])
        old = Json.object(previous.get("samples"))
        failures = [
            name
            for name in current
            if PerformanceGate.regression(
                [Json.number(value) for value in Json.array(current[name])],
                [Json.number(value) for value in Json.array(old.get(name))],
            )
        ]
        report["regressions"] = Json.value(failures)
        report["baseline_status"] = "compared"
        return not failures


if __name__ == "__main__":
    QualityApplication.main()
