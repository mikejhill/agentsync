"""Run actionlint with project-owned runner configuration from pyproject.toml."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import yaml

from agentsync.jsonutil import Json


class WorkflowChecks:
    """Validate complete workflow syntax while declaring dedicated runner labels."""

    @staticmethod
    def main() -> None:
        """Use a supplied verified executable or the exact pinned Go module version."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--executable", type=Path)
        arguments = parser.parse_args()
        metadata = Json.record(
            tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        )
        configuration = dict(Json.object(Json.object(metadata["tool"])["actionlint"]))
        version = Json.string(configuration.pop("version"))
        command = (
            [str(arguments.executable)]
            if arguments.executable
            else ["go", "run", f"github.com/rhysd/actionlint/cmd/actionlint@v{version}"]
        )
        with tempfile.TemporaryDirectory(prefix="agentsync-actionlint-") as directory:
            file = Path(directory) / "actionlint.yaml"
            file.write_text(yaml.safe_dump(configuration), encoding="utf-8")
            result = subprocess.run(  # noqa: S603 - fixed tool argv and declared labels
                [*command, "-config-file", str(file), "-color"],
                check=False,
                timeout=180,
            )
        sys.exit(result.returncode)


if __name__ == "__main__":
    WorkflowChecks.main()
