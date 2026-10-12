"""Restore installation-time XDG roots before background CLI execution."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from skillsinc.__main__ import Application
from skillsinc.jsonutil import Json


class ServiceRunner:
    """Keep native login managers independent of inherited shell environment."""

    @staticmethod
    def main() -> None:
        """Load explicit environment and run the ordinary foreground watcher."""
        environment = Json.object(
            Json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        )
        allowed = {
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_STATE_HOME",
            "XDG_CACHE_HOME",
        }
        for key, value in environment.items():
            if key in allowed:
                os.environ[key] = Json.string(value)
        sys.exit(Application().run(sys.argv[2:]))


if __name__ == "__main__":
    ServiceRunner.main()
