"""Complete local and commit-addressed Git source snapshots."""

from __future__ import annotations

import io
import os
import stat
import subprocess
import tarfile
from pathlib import Path

from filelock import FileLock

from agentsync.config import Source
from agentsync.exceptions import SourceError
from agentsync.jsonutil import Json
from agentsync.models import Digest, PackageFile, Snapshot
from agentsync.paths import SafePath


class LocalSource:
    """Scan stable trees without silently accepting incomplete enumeration."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def snapshot(self) -> Snapshot:
        """Read all regular files and verify tree stability."""
        try:
            before = self._inventory()
            files = tuple(
                PackageFile(name, path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                for name, path, _, _ in before
            )
            if before != self._inventory():
                raise SourceError(f"Source changed while reading: {self.root}")
        except OSError as error:
            raise SourceError(f"Incomplete source scan: {self.root}") from error
        fingerprint = b"".join(
            file.path.encode()
            + b"\0"
            + file.mode.to_bytes(4)
            + len(file.content).to_bytes(8)
            + file.content
            for file in files
        )
        return Snapshot(self.root, Digest.of(fingerprint), files)

    def _inventory(self) -> tuple[tuple[str, Path, int, int], ...]:
        """Enumerate with explicit permission and symlink errors."""
        if not self.root.is_dir() or self.root.is_symlink() or self.root.is_junction():
            raise SourceError(f"Source directory unavailable: {self.root}")
        result = []
        for directory, folders, files in os.walk(self.root, onerror=self._scan_error):
            folders[:] = sorted(folder for folder in folders if folder != ".git")
            self._validate_links(Path(directory), folders)
            for name in sorted(files):
                path = Path(directory) / name
                if path.is_symlink() or not path.is_file():
                    raise SourceError(
                        f"Only regular source files are supported: {path}"
                    )
                info = path.stat()
                relative = SafePath.relative(path.relative_to(self.root).as_posix())
                result.append((relative, path, info.st_mtime_ns, info.st_size))
        return tuple(sorted(result))

    @staticmethod
    def _validate_links(directory: Path, folders: list[str]) -> None:
        """Reject directory links rather than omit their content."""
        for name in folders:
            path = directory / name
            if path.is_symlink() or path.is_junction():
                raise SourceError(f"Source directory link: {directory / name}")

    @staticmethod
    def _scan_error(error: OSError) -> None:
        """Turn walk failures into authoritative snapshot failure."""
        raise SourceError("Source enumeration failed") from error


class GitSource:
    """Fetch immutable snapshots without checkout hooks or submodules."""

    def __init__(self, source: Source, cache: Path, *, fetch: bool = True) -> None:
        self.source = source
        self.root = cache / "git" / Digest.of(source.location.encode())
        self.fetch = fetch

    def snapshot(self) -> Snapshot:
        """Fetch and archive one validated revision."""
        if not self.fetch:
            if not self.root.is_dir():
                raise SourceError("Git mirror unavailable; run sync to fetch it")
            return self._snapshot_locked()
        self.root.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.root) + ".lock"):
            return self._snapshot_locked()

    def _snapshot_locked(self) -> Snapshot:
        """Resolve refs only after a successful fetch."""
        options = self.source.options or {}
        if not self.root.exists():
            if not self.fetch:
                raise SourceError("Git mirror unavailable; run sync to fetch it")
            self._git("clone", "--bare", "--", self.source.location, str(self.root))
        elif self.fetch:
            self._git(
                "-C",
                str(self.root),
                "fetch",
                "--prune",
                "origin",
                "+refs/heads/*:refs/heads/*",
                "+refs/tags/*:refs/tags/*",
            )
            if "ref" not in options:
                self._refresh_default_branch()
        ref = Json.string(options.get("ref", "HEAD"))
        if ref.startswith("-"):
            raise SourceError("Git ref must not be an option")
        revision = (
            self._git("-C", str(self.root), "rev-parse", "--verify", ref + "^{commit}")
            .decode()
            .strip()
        )
        archive = self._git("-C", str(self.root), "archive", "--format=tar", revision)
        self._validate_tree(revision)
        files = []
        with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
            for member in stream.getmembers():
                if member.isdir():
                    continue
                if not member.isfile():
                    raise SourceError(
                        f"Git source contains unsupported link: {member.name}"
                    )
                content = stream.extractfile(member)
                if content is None:
                    raise SourceError(f"Cannot read archive member {member.name}")
                files.append(
                    PackageFile(
                        SafePath.relative(member.name), content.read(), member.mode
                    )
                )
        return Snapshot(self.root, revision, tuple(files))

    def _validate_tree(self, revision: str) -> None:
        """Reject omitted submodule contents as an incomplete resource snapshot."""
        tree = self._git("-C", str(self.root), "ls-tree", "-r", "-z", revision)
        if any(entry.startswith(b"160000 ") for entry in tree.split(b"\0")):
            raise SourceError(
                "Git submodule contents are unavailable; source snapshot incomplete"
            )

    def _refresh_default_branch(self) -> None:
        """Follow a changed remote default branch after a successful fetch."""
        advertised = self._git(
            "-C", str(self.root), "ls-remote", "--symref", "origin", "HEAD"
        ).decode()
        for line in advertised.splitlines():
            if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
                branch = line.removeprefix("ref: ").split("\t", 1)[0]
                self._git("-C", str(self.root), "symbolic-ref", "HEAD", branch)
                return
        raise SourceError("Remote default branch cannot be resolved")

    @staticmethod
    def _git(*arguments: str) -> bytes:
        """Execute Git with checkout hooks disabled and bounded time."""
        command = [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "protocol.ext.allow=never",
            "-c",
            "core.longpaths=true",
            *arguments,
        ]
        try:
            result = subprocess.run(  # noqa: S603 - explicit trusted argv, no shell
                command, capture_output=True, check=True, timeout=120
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise SourceError(
                "Git fetch/archive failed; previous output retained"
            ) from error
        return result.stdout
