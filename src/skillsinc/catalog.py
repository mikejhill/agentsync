"""Install versioned bundled policy data independently of application settings."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path


class Catalog:
    """Publish schema, recipe, and evidence descriptors without replacing user data."""

    @staticmethod
    def install(root: Path) -> None:
        """Create missing versioned catalog files on default initialization."""
        root.mkdir(parents=True, exist_ok=True)
        for name in ("config.schema.json", "default-recipe.json", "contracts-v1.json"):
            resource = files("skillsinc").joinpath("data", name)
            Catalog._create(root / name, resource.read_text(encoding="utf-8"))

    @staticmethod
    def _create(file: Path, text: str) -> None:
        """Preserve existing policy data on repeated initialization."""
        try:
            with file.open("x", encoding="utf-8") as stream:
                stream.write(text)
        except FileExistsError:
            return
