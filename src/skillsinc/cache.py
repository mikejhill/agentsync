"""Versioned rendered-output cache with deterministic package fingerprints."""

from __future__ import annotations

import logging
from pathlib import Path

from skillsinc import EXTENSION_API_VERSION, __version__
from skillsinc.config import Destination, Step
from skillsinc.exceptions import AppError
from skillsinc.jsonutil import Json, JsonObject
from skillsinc.models import Customization, Digest, Output
from skillsinc.transactions import OutputCodec

logger = logging.getLogger(__name__)


class ConversionCache:
    """Cache pure built-in conversion proposals, never ownership decisions."""

    def __init__(self, root: Path) -> None:
        self.root = root / "conversions"

    @staticmethod
    def key(
        items: tuple[Customization, ...],
        destination: Destination,
        steps: tuple[Step, ...],
        policy: JsonObject,
    ) -> str:
        """Bind cache entries to input bytes, pipeline, contract, and app versions."""
        data = {
            "application": __version__,
            "extension_api": EXTENSION_API_VERSION,
            "destination": {
                "name": destination.name,
                "path": str(destination.location),
                "profile": destination.profile,
                "scope": destination.scope,
                "options": destination.options,
                "version": destination.version,
            },
            "pipeline": [{"use": step.use, "options": step.options} for step in steps],
            "policy": policy,
            "items": [
                {
                    "name": item.name,
                    "kind": item.kind,
                    "source": item.source,
                    "origins": list(item.origins),
                    "style": item.style,
                    "metadata": item.metadata,
                    "files": [
                        {
                            "path": file.path,
                            "mode": file.mode,
                            "digest": Digest.of(file.content),
                        }
                        for file in item.files
                    ],
                }
                for item in items
            ],
        }
        return Digest.of(Json.dumps(data).encode())

    def get(self, key: str) -> tuple[tuple[Output, ...], list[str]] | None:
        """Ignore corrupt cache entries and render from authoritative sources."""
        file = self.root / (key + ".json")
        if not file.exists():
            return None
        try:
            data = Json.object(Json.loads(file.read_text(encoding="utf-8")))
            if data.get("version") != 1:
                return None
            if data.get("checksum") != Digest.of(
                Json.dumps(data.get("outputs")).encode()
            ):
                return None
            outputs = tuple(
                OutputCodec.decode(Json.object(raw))
                for raw in Json.array(data.get("outputs"))
            )
            return outputs, list(Json.strings(data.get("diagnostics")))
        except (AppError, ValueError, OSError, UnicodeError) as error:
            logger.warning("Ignoring invalid conversion cache: %s", error)
            return None

    def put(self, key: str, outputs: tuple[Output, ...], notes: list[str]) -> None:
        """Persist disposable conversion results by atomic replacement."""
        self.root.mkdir(parents=True, exist_ok=True)
        file = self.root / (key + ".json")
        temporary = file.with_suffix(".tmp")
        records = [OutputCodec.encode(output) for output in outputs]
        temporary.write_text(
            Json.dumps(
                {
                    "version": 1,
                    "outputs": records,
                    "checksum": Digest.of(Json.dumps(records).encode()),
                    "diagnostics": notes,
                }
            ),
            encoding="utf-8",
        )
        temporary.replace(file)
