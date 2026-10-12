"""Validate documentation, workflow boundaries, and release metadata."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path
from zipfile import ZipFile

import yaml

from skillsinc import __version__
from skillsinc.config import Configuration
from skillsinc.exceptions import ConfigurationError
from skillsinc.jsonutil import Json
from skillsinc.paths import XdgPaths


class RepositoryChecks:
    """Read-only repository and release checks shared by local and CI gates."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def run(self, tag: str | None = None, distribution: Path | None = None) -> None:
        """Check links, configuration examples, workflow permissions, and versions."""
        self.documentation()
        self.workflows()
        self.version(tag)
        example = self.root / "docs/config.example.json"
        paths = XdgPaths(
            *(self.root / folder for folder in ("config", "data", "state", "cache"))
        )
        Configuration(paths).parse(
            Json.object(Json.loads(example.read_text(encoding="utf-8"))), example
        )
        if distribution is not None:
            self.package(distribution)

    def documentation(self) -> None:
        """Reject broken relative Markdown links without network access."""
        files = (*self.root.glob("*.md"), *(self.root / "docs").rglob("*.md"))
        for file in files:
            for target in re.findall(
                r"\[[^\]]*\]\(([^)]+)\)", file.read_text(encoding="utf-8")
            ):
                path = target.strip("<>").split("#", 1)[0]
                if not path or re.match(r"[a-z]+:", path):
                    continue
                linked = (file.parent / path).resolve()
                if not linked.is_relative_to(self.root) or not linked.exists():
                    raise ConfigurationError(
                        f"Broken local documentation link: {file.name}: {target}"
                    )

    def workflows(self) -> None:
        """Enforce SHA pins and prohibit privileged pull-request execution."""
        for file in (self.root / ".github/workflows").glob("*.yml"):
            text = file.read_text(encoding="utf-8")
            # Preserve "on" without constructing Python objects.
            raw = yaml.load(
                text,
                Loader=yaml.BaseLoader,  # noqa: S506 - no Python object constructors
            )
            document = Json.object(Json.value(raw))
            triggers = document.get("on", {})
            if isinstance(triggers, dict) and "pull_request_target" in triggers:
                raise ConfigurationError(
                    f"Privileged PR trigger forbidden: {file.name}"
                )
            for action in re.findall(r"(?m)^\s*(?:-\s*)?uses:\s*([^\s#]+)", text):
                if action.startswith("./"):
                    continue
                if not re.fullmatch(r"[\w.-]+/[\w./-]+@[a-f0-9]{40}", action):
                    raise ConfigurationError(f"Unpinned action: {file.name}: {action}")
            permissions = Json.object(document.get("permissions", {}))
            if permissions.get("contents") != "read" or "id-token" in permissions:
                raise ConfigurationError(
                    f"Workflow permissions must default to read-only: {file.name}"
                )

    def version(self, tag: str | None = None) -> str:
        """Reject divergence between package, runtime, and release tag versions."""
        metadata = Json.record(
            tomllib.loads((self.root / "pyproject.toml").read_text(encoding="utf-8"))
        )
        project = Json.object(metadata["project"])
        version = Json.string(project["version"])
        if version != __version__:
            raise ConfigurationError(
                "pyproject.toml and skillsinc.__version__ disagree"
            )
        if tag is not None and tag != f"v{version}":
            raise ConfigurationError(f"Release tag must be v{version}")
        return version

    @staticmethod
    def package(directory: Path) -> None:
        """Ensure wheels contain typed code, contracts, and license metadata."""
        wheels = tuple(directory.glob("*.whl"))
        if len(wheels) != 1 or len(tuple(directory.glob("*.tar.gz"))) != 1:
            raise ConfigurationError("Expected one wheel and one source distribution")
        with ZipFile(wheels[0]) as archive:
            names = set(archive.namelist())
            required = {
                "skillsinc/__main__.py",
                "skillsinc/py.typed",
                "skillsinc/data/config.schema.json",
                "skillsinc/data/contracts-v1.json",
                "skillsinc/data/default-recipe.json",
            }
            if not required <= names or not any(
                name.endswith("/licenses/LICENSE") for name in names
            ):
                raise ConfigurationError(
                    "Wheel is missing code, contract data, or license"
                )

    @classmethod
    def main(cls) -> None:
        """Run concise maintainer checks with scheduler-compatible failure exits."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--tag")
        parser.add_argument("--dist", type=Path)
        arguments = parser.parse_args()
        try:
            cls(Path.cwd()).run(arguments.tag, arguments.dist)
        except (ConfigurationError, OSError, ValueError) as error:
            sys.stderr.write(f"Repository check failed: {error}\n")
            raise SystemExit(1) from error
        sys.stdout.write("Repository checks passed\n")


if __name__ == "__main__":
    RepositoryChecks.main()
