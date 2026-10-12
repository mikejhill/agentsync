"""Convert untyped library output to validated JSON values."""

from __future__ import annotations

import builtins
import json

from skillsinc.exceptions import ConfigurationError

type JsonValue = (
    str | int | float | bool | list[JsonValue] | dict[str, JsonValue] | None
)
type JsonObject = dict[str, JsonValue]


class Json:
    """Typed boundary and extraction helpers."""

    @classmethod
    def value(cls, value: builtins.object) -> JsonValue:
        """Validate library output recursively."""
        if value is None or isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, list):
            return [cls.value(item) for item in value]
        if isinstance(value, dict) and all(isinstance(key, str) for key in value):
            return {str(key): cls.value(item) for key, item in value.items()}
        raise ConfigurationError("Expected JSON-compatible data")

    @classmethod
    def loads(cls, text: str) -> JsonValue:
        """Decode JSON."""
        try:
            return cls.value(json.loads(text))
        except (ValueError, RecursionError) as error:
            raise ConfigurationError("Invalid JSON document") from error

    @staticmethod
    def object(value: JsonValue) -> JsonObject:
        """Require an object."""
        if not isinstance(value, dict):
            raise ConfigurationError("Expected an object")
        return value

    @staticmethod
    def array(value: JsonValue) -> list[JsonValue]:
        """Require an array."""
        if not isinstance(value, list):
            raise ConfigurationError("Expected an array")
        return value

    @staticmethod
    def string(value: JsonValue) -> str:
        """Require a string."""
        if not isinstance(value, str):
            raise ConfigurationError("Expected a string")
        return value

    @classmethod
    def strings(cls, value: JsonValue) -> tuple[str, ...]:
        """Require a string array."""
        return tuple(cls.string(item) for item in cls.array(value))

    @staticmethod
    def number(value: JsonValue) -> float:
        """Require a positive number."""
        if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
            raise ConfigurationError("Expected a positive number")
        return float(value)

    @staticmethod
    def boolean(value: JsonValue) -> bool:
        """Require a boolean."""
        if not isinstance(value, bool):
            raise ConfigurationError("Expected a boolean")
        return value

    @staticmethod
    def dumps(value: builtins.object) -> str:
        """Encode stable JSON."""
        return (
            json.dumps(Json.value(value), indent=2, ensure_ascii=False, sort_keys=True)
            + "\n"
        )

    @classmethod
    def record(cls, value: builtins.object) -> JsonObject:
        """Normalize collection invariance at report construction boundaries."""
        return cls.object(cls.value(value))
