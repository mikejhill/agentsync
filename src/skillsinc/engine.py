"""Route planning and shared CLI/background reconciliation orchestration."""

from __future__ import annotations

import importlib.metadata
import tempfile
import unicodedata
from contextlib import ExitStack
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from filelock import FileLock

from skillsinc.cache import ConversionCache
from skillsinc.config import Destination, Route, Settings, Source, Step
from skillsinc.contracts import ContractRegistry, HarnessRenderer
from skillsinc.exceptions import (
    AppError,
    ConfigurationError,
    ConflictError,
    ConversionError,
    SourceError,
)
from skillsinc.jsonutil import Json, JsonObject, JsonValue
from skillsinc.models import (
    Customization,
    CustomizationReader,
    DestinationRenderer,
    Digest,
    Output,
    Snapshot,
    SourceProvider,
)
from skillsinc.paths import XdgPaths
from skillsinc.readers import PackageReader
from skillsinc.reconcile import Reconciler
from skillsinc.sources import GitSource, LocalSource
from skillsinc.state import OwnershipStore
from skillsinc.transactions import TransactionManager
from skillsinc.transforms import Selection, TransformRegistry


@dataclass(frozen=True, slots=True)
class DistributionPlan:
    """Validated proposed outputs and per-target failures."""

    outputs: tuple[Output, ...]
    blocked: dict[str, str]
    snapshots: dict[str, Snapshot]
    diagnostics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RunContext:
    """Shared policy and ownership for a distribution run."""

    settings: Settings
    owner: str
    records: dict[str, tuple[str, Output]]


class ExtensionRegistry:
    """Trusted installed providers/readers/renderers with typed boundaries."""

    @staticmethod
    def load(group: str, name: str, *args: object) -> object:
        """Instantiate one unambiguous installed entry point."""
        entries = importlib.metadata.entry_points(group=group, name=name)
        if len(entries) != 1:
            raise ConfigurationError(f"Unknown or ambiguous extension {group}:{name}")
        result: object = entries[0].load()(*args)
        return result


class DistributionPlanner:
    """Resolve source collections and explicit target pipelines."""

    def __init__(
        self, paths: XdgPaths, transforms: TransformRegistry | None = None
    ) -> None:
        self.paths = paths
        self.transforms = transforms or TransformRegistry()
        self.cache = ConversionCache(paths.cache)
        self.cache_write = False
        self.revisions: JsonObject = {}

    def provider(self, source: Source, *, fetch: bool = True) -> SourceProvider:
        """Resolve a built-in or installed provider."""
        if source.provider == "local":
            return LocalSource(Path(source.location))
        if source.provider == "git":
            return GitSource(source, self.paths.cache, fetch=fetch)
        instance = ExtensionRegistry.load(
            "skillsinc.sources", source.provider, source, self.paths.cache
        )
        # Trusted provider entry points implement the documented structural protocol.
        return cast(SourceProvider, instance)

    def build(
        self, settings: Settings, targets: tuple[str, ...] = (), *, fetch: bool = False
    ) -> DistributionPlan:
        """Render each target completely before any commit."""
        if targets and set(targets) - {item.name for item in settings.destinations}:
            raise ConfigurationError("Unknown selected target")
        self._validate_roots(settings)
        snapshots, collections, failures = self._sources(settings, fetch=fetch)
        self.revisions = {
            name: snapshot.revision for name, snapshot in snapshots.items()
        }
        blocked: dict[str, str] = {}
        outputs = []
        diagnostics = []
        for destination in settings.destinations:
            if not destination.enabled or (targets and destination.name not in targets):
                continue
            try:
                proposed, notes = self._destination(
                    destination, settings, collections, failures
                )
                self._validate_outputs(proposed, settings)
                outputs.extend(proposed)
                diagnostics.extend(notes)
            except AppError as error:
                blocked[destination.name] = str(error)
        return self._deduplicate(tuple(outputs), blocked, snapshots, tuple(diagnostics))

    @staticmethod
    def _validate_outputs(outputs: list[Output], settings: Settings) -> None:
        """Check sibling documents and plugin paths for source feedback cycles."""
        roots = tuple(
            Path(source.location).resolve()
            for source in settings.sources
            if source.provider == "local"
        )
        for output in outputs:
            if not output.path.is_absolute():
                raise ConfigurationError("Renderer output paths must be absolute")
            if any(output.canonical.is_relative_to(root) for root in roots):
                raise ConflictError(f"Output would modify a source: {output.path}")

    def _sources(
        self, settings: Settings, *, fetch: bool
    ) -> tuple[
        dict[str, Snapshot], dict[str, tuple[Customization, ...]], dict[str, str]
    ]:
        """Read each source once and retain its failure provenance."""
        snapshots = {}
        collections = {}
        failures = {}
        for source in settings.sources:
            try:
                snapshot = self.provider(source, fetch=fetch).snapshot()
                snapshots[source.name] = snapshot
                reader: CustomizationReader = PackageReader()
                if source.reader != "default":
                    # Reader plugins are installed trusted structural collaborators.
                    reader = cast(
                        CustomizationReader,
                        ExtensionRegistry.load("skillsinc.readers", source.reader),
                    )
                collections[source.name] = tuple(
                    item
                    for item in reader.read(snapshot, source.name, source.style)
                    if Selection.matches(item, source.select)
                )
            except (AppError, UnicodeError, OSError) as error:
                failures[source.name] = (
                    f"Source {source.name} unavailable or invalid: {error}"
                )
        return snapshots, collections, failures

    def _destination(
        self,
        destination: Destination,
        settings: Settings,
        collections: dict[str, tuple[Customization, ...]],
        failures: dict[str, str],
    ) -> tuple[list[Output], list[str]]:
        """Apply route steps then destination steps in explicit order."""
        outputs = []
        notes = []
        for route in settings.routes:
            if destination.name not in route.destinations:
                continue
            unavailable = [failures[name] for name in route.sources if name in failures]
            if unavailable:
                raise SourceError("; ".join(unavailable))
            items = tuple(
                item
                for name in route.sources
                for item in collections[name]
                if Selection.matches(item, route.select)
            )
            steps = (
                *route.steps,
                *destination.steps,
            )
            converted, diagnostics = self._convert(destination, items, steps, route)
            outputs.extend(converted)
            notes.extend(diagnostics)
        return outputs, notes

    def _convert(
        self,
        destination: Destination,
        items: tuple[Customization, ...],
        steps: tuple[Step, ...],
        route: Route,
    ) -> tuple[tuple[Output, ...], list[str]]:
        """Cache only pure built-in pipelines; plugin execution remains explicit."""
        eligible = (
            all(step.use in TransformRegistry.BUILTINS for step in steps)
            and (destination.options or {}).get("renderer") is None
        )
        key = self.cache.key(
            items,
            destination,
            steps,
            {
                "route": route.name,
                "approximate": route.approximate,
                "unsupported": route.unsupported,
                "revisions": self.revisions,
                "contract_version": ContractRegistry.get(destination.profile).version
                if eligible
                else None,
            },
        )
        cached = self.cache.get(key) if eligible else None
        if cached is not None:
            return cached
        items = self.transforms.apply(items, steps)
        renderer = self._renderer(destination, approximate=route.approximate)
        outputs: list[Output] = []
        notes: list[str] = []
        for item in items:
            self._render_item(renderer, item, route, outputs, notes)
        trace = tuple(
            f"transform:{index}:{step.use}" for index, step in enumerate(steps, start=1)
        )
        outputs = [
            replace(output, provenance=(*output.provenance, *trace))
            for output in outputs
        ]
        if self.cache_write and eligible:
            self.cache.put(key, tuple(outputs), notes)
        return tuple(outputs), notes

    @staticmethod
    def _renderer(
        destination: Destination, *, approximate: bool
    ) -> DestinationRenderer:
        """Choose a native or explicitly configured custom writer."""
        name = (destination.options or {}).get("renderer")
        if name is not None:
            # Central reconciliation owns writes from trusted renderer plugins.
            return cast(
                DestinationRenderer,
                ExtensionRegistry.load(
                    "skillsinc.renderers", Json.string(name), destination
                ),
            )
        return HarnessRenderer(destination, approximate=approximate)

    @staticmethod
    def _render_item(
        renderer: DestinationRenderer,
        item: Customization,
        route: Route,
        outputs: list[Output],
        notes: list[str],
    ) -> None:
        """Retain explicit exclusions as visible diagnostics."""
        try:
            outputs.extend(
                replace(
                    output,
                    provenance=(
                        *output.provenance,
                        "route:" + route.name,
                        *("input:" + origin for origin in item.origins),
                    ),
                )
                for output in renderer.render(item)
            )
            if isinstance(renderer, HarnessRenderer):
                notes.extend(renderer.diagnostics)
        except ConversionError as error:
            if route.unsupported != "exclude":
                raise
            notes.append(f"Excluded {item.kind}/{item.name}: {error}")

    @staticmethod
    def _validate_roots(settings: Settings) -> None:
        """Reject local feedback cycles and ambiguous selected targets."""
        for source in settings.sources:
            if source.provider != "local":
                continue
            root = Path(source.location).resolve()
            for destination in settings.destinations:
                target = destination.location.resolve()
                if destination.enabled and (
                    root.is_relative_to(target) or target.is_relative_to(root)
                ):
                    raise ConfigurationError(
                        f"Source/destination overlap: {source.name}, {destination.name}"
                    )
        for destination in settings.destinations:
            if (
                destination.enabled
                and (destination.options or {}).get("renderer") is None
            ):
                ContractRegistry.get(destination.profile)

    @staticmethod
    def _deduplicate(
        outputs: tuple[Output, ...],
        blocked: dict[str, str],
        snapshots: dict[str, Snapshot],
        diagnostics: tuple[str, ...],
    ) -> DistributionPlan:
        """Reject incompatible writes and portable case-fold collisions."""
        unique: dict[str, Output] = {}
        folded: dict[str, Output] = {}
        physical: dict[str, list[Output]] = {}
        for output in outputs:
            path_key = unicodedata.normalize("NFC", str(output.canonical)).casefold()
            for other in physical.get(path_key, []):
                if other.slot != output.slot and (
                    not other.slot
                    or not output.slot
                    or other.slot[: len(output.slot)] == output.slot
                    or output.slot[: len(other.slot)] == other.slot
                    or other.format != output.format
                ):
                    blocked[output.target] = (
                        f"Overlapping proposed output {output.path}"
                    )
                    blocked[other.target] = f"Overlapping proposed output {output.path}"
            physical.setdefault(path_key, []).append(output)
            existing = unique.get(output.key)
            folded_key = path_key + "#" + Json.dumps(list(output.slot)).strip()
            case_alias = folded.get(folded_key)
            if (
                existing is not None
                and (
                    existing.content != output.content
                    or existing.mode != output.mode
                    or existing.format != output.format
                )
            ) or (case_alias is not None and case_alias.key != output.key):
                conflicting = existing or case_alias
                assert conflicting is not None  # noqa: S101 -- internal invariant after the collision guard.
                blocked[output.target] = f"Conflicting output {output.path}"
                blocked[conflicting.target] = f"Conflicting output {output.path}"
            else:
                unique[output.key] = (
                    output
                    if existing is None
                    else replace(
                        existing,
                        provenance=tuple(
                            sorted(set(existing.provenance + output.provenance))
                        ),
                    )
                )
                folded[folded_key] = output
        return DistributionPlan(outputs, blocked, snapshots, diagnostics)


class Engine:
    """One distribution engine for manual and background execution."""

    def __init__(
        self, paths: XdgPaths, planner: DistributionPlanner | None = None
    ) -> None:
        self.paths = paths
        self.planner = planner or DistributionPlanner(paths)
        self.store = OwnershipStore(paths.state)

    def run(
        self,
        settings: Settings,
        targets: tuple[str, ...] = (),
        *,
        apply: bool = False,
        adopt: bool = False,
        fetch: bool = True,
    ) -> JsonObject:
        """Plan or apply source-authoritative distribution."""
        if targets and set(targets) - {item.name for item in settings.destinations}:
            raise ConfigurationError("Unknown selected target")
        if not apply:
            return self._run(settings, targets, apply=False, adopt=adopt, fetch=fetch)
        self.paths.state.mkdir(parents=True, exist_ok=True)
        locks = Path(tempfile.gettempdir()) / "skillsinc-locks"
        locks.mkdir(parents=True, exist_ok=True)
        with ExitStack() as stack:
            stack.enter_context(FileLock(str(locks / "distribution.lock"), timeout=30))
            stack.enter_context(
                FileLock(str(self.paths.state / "engine.lock"), timeout=30)
            )
            roots = sorted(
                {
                    str(destination.location.resolve())
                    for destination in settings.destinations
                    if destination.enabled
                }
            )
            for root in roots:
                stack.enter_context(
                    FileLock(str(locks / Digest.of(root.encode())), timeout=30)
                )
            TransactionManager(self.store).recover()
            return self._run(settings, targets, apply=True, adopt=adopt, fetch=fetch)

    def _run(
        self,
        settings: Settings,
        targets: tuple[str, ...],
        *,
        apply: bool,
        adopt: bool,
        fetch: bool,
    ) -> JsonObject:
        """Reconcile connected target groups independently."""
        self.planner.cache_write = apply
        plan = self.planner.build(settings, fetch=fetch if apply else False)
        records = self.store.records()
        owner = str(settings.file.resolve())
        selected = {destination.name for destination in settings.destinations}
        selected |= {
            output.target
            for record_owner, output in records.values()
            if record_owner == owner
        }
        context = RunContext(settings, owner, records)
        results: list[JsonValue] = [
            self._group(group, plan, context, apply=apply, adopt=adopt)
            for group in self._groups(
                selected,
                (
                    *plan.outputs,
                    *(
                        Output(
                            destination.location / ".skillsinc-commit-group",
                            b"",
                            destination.name,
                            (),
                        )
                        for destination in settings.destinations
                    ),
                ),
                records,
                owner,
            )
            if not targets or group & set(targets)
        ]
        report: JsonObject = {
            "version": 1,
            "config": owner,
            "applied": apply,
            "ok": all(Json.object(result).get("ok") for result in results),
            "targets": results,
            "diagnostics": list(plan.diagnostics),
            "sources": {
                name: snapshot.revision for name, snapshot in plan.snapshots.items()
            },
        }
        if apply:
            self.store.report(report)
        return report

    def _group(
        self,
        group: set[str],
        plan: DistributionPlan,
        context: RunContext,
        *,
        apply: bool,
        adopt: bool,
    ) -> JsonObject:
        """Retain all previous output if a commit group is blocked."""
        reasons = [reason for target, reason in plan.blocked.items() if target in group]
        if reasons:
            return Json.record(
                {"names": sorted(group), "ok": False, "error": "; ".join(reasons)}
            )
        outputs = tuple(output for output in plan.outputs if output.target in group)
        try:
            operations = Reconciler().plan(
                context.owner, group, outputs, context.records, adopt=adopt
            )
            if apply:
                self._recheck(context.settings, plan)
                TransactionManager(self.store).apply(
                    context.owner, group, operations, outputs
                )
            return Json.record(
                {
                    "names": sorted(group),
                    "ok": True,
                    "operations": [
                        {
                            "path": str(operation.path),
                            "action": "delete"
                            if operation.after is None
                            else "create"
                            if operation.before is None
                            else "update",
                        }
                        for operation in operations
                    ],
                    "outputs": [
                        {
                            "path": str(output.path),
                            "slot": list(output.slot),
                            "provenance": list(output.provenance),
                        }
                        for output in outputs
                    ],
                }
            )
        except (AppError, OSError) as error:
            return Json.record(
                {"names": sorted(group), "ok": False, "error": str(error)}
            )

    def _recheck(self, settings: Settings, plan: DistributionPlan) -> None:
        """Verify local revisions have not changed during conversion."""
        for source in settings.sources:
            if source.name in plan.snapshots and (
                self.planner.provider(source, fetch=False).snapshot().revision
                != plan.snapshots[source.name].revision
            ):
                raise ConflictError(f"Source changed after planning: {source.name}")

    @staticmethod
    def _groups(
        selected: set[str],
        outputs: tuple[Output, ...],
        records: dict[str, tuple[str, Output]],
        owner: str,
    ) -> list[set[str]]:
        """Connect targets that share a proposed or previously owned file."""
        groups: list[set[str]] = [{target} for target in sorted(selected)]
        files: dict[Path, set[str]] = {}
        previous = tuple(
            output for record_owner, output in records.values() if record_owner == owner
        )
        for output in (*outputs, *previous):
            files.setdefault(output.canonical, set()).add(output.target)
        for members in files.values():
            connected = [group for group in groups if group & members]
            if connected:
                union: set[str] = set()
                for member_group in connected:
                    union.update(member_group)
                retained: list[set[str]] = [
                    group for group in groups if group not in connected
                ]
                retained.append(union)
                groups = retained
        return groups
