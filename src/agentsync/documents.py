"""Owned-entry edits preserving unrelated structured document content."""

from __future__ import annotations

import re
from collections.abc import MutableMapping
from typing import cast

import json5
import tomlkit
from tomlkit.exceptions import ParseError

from agentsync.exceptions import ConfigurationError
from agentsync.jsonutil import Json, JsonObject, JsonValue


class JsoncEditor:
    """Token-span edits for standard JSON with comments and trailing commas."""

    TOKEN = re.compile(
        r'\s+|//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|[^\s{}\[\],:]+|[{}\[\],:]',
        re.MULTILINE,
    )

    def replace(
        self,
        text: str,
        slot: tuple[str, ...],
        value: JsonValue,
        *,
        remove: bool = False,
    ) -> str:
        """Edit one property while preserving unrelated tokens."""
        tokens = [
            (match.group(), match.start(), match.end())
            for match in self.TOKEN.finditer(text)
            if not match.group().isspace()
            and not match.group().startswith(("//", "/*"))
        ]
        if not tokens or tokens[0][0] != "{":
            raise ConfigurationError("JSON configuration must be an object")
        spans: dict[tuple[str, ...], tuple[int, int, int, int]] = {}
        ends: dict[tuple[str, ...], int] = {}
        self._object(tokens, 0, (), spans, ends)
        if slot in spans:
            key_start, start, end, property_end = spans[slot]
            if not remove:
                return text[:start] + Json.dumps(value).strip() + text[end:]
            return self._remove(text, key_start, property_end)
        if remove:
            return text
        parent = slot[:-1]
        if parent not in ends:
            if parent in spans:
                raise ConfigurationError("Slot parent must be an object")
            missing = next(
                index for index in range(len(slot)) if slot[: index + 1] not in spans
            )
            nested = value
            for key in reversed(slot[missing + 1 :]):
                nested = {key: nested}
            return self.replace(text, slot[: missing + 1], nested)
        end = ends[parent]
        previous = next(token[0] for token in reversed(tokens) if token[2] <= end)
        comma = "" if previous in ("{", ",") else ","
        insertion = (
            comma
            + "\n"
            + Json.dumps(slot[-1]).strip()
            + ": "
            + Json.dumps(value).strip()
            + "\n"
        )
        return text[:end] + insertion + text[end:]

    @classmethod
    def _object(
        cls,
        tokens: list[tuple[str, int, int]],
        index: int,
        path: tuple[str, ...],
        spans: dict[tuple[str, ...], tuple[int, int, int, int]],
        ends: dict[tuple[str, ...], int],
    ) -> int:
        """Collect object-member spans recursively."""
        index += 1
        while tokens[index][0] != "}":
            key_token, key_start, _ = tokens[index]
            key = Json.string(Json.loads(key_token))
            if tokens[index + 1][0] != ":":
                raise ConfigurationError("Invalid JSON member")
            index += 2
            start = tokens[index][1]
            member = (*path, key)
            index = cls._value_end(tokens, index, member, spans, ends)
            end = tokens[index - 1][2]
            property_end = tokens[index][2] if tokens[index][0] == "," else end
            spans[member] = (key_start, start, end, property_end)
            if tokens[index][0] == ",":
                index += 1
        ends[path] = tokens[index][1]
        return index + 1

    @classmethod
    def _value_end(
        cls,
        tokens: list[tuple[str, int, int]],
        index: int,
        path: tuple[str, ...],
        spans: dict[tuple[str, ...], tuple[int, int, int, int]],
        ends: dict[tuple[str, ...], int],
    ) -> int:
        """Skip a scalar or array while recursing through objects."""
        if tokens[index][0] == "{":
            return cls._object(tokens, index, path, spans, ends)
        if tokens[index][0] != "[":
            return index + 1
        depth = 1
        index += 1
        while depth:
            symbol = tokens[index][0]
            depth += int(symbol == "[") - int(symbol == "]")
            index += 1
        return index

    @staticmethod
    def _remove(text: str, start: int, end: int) -> str:
        """Remove an entry and the appropriate adjacent separator."""
        if text[start:end].rstrip().endswith(","):
            return text[:start] + text[end:]
        prefix = text[:start]
        comma = prefix.rstrip().rfind(",")
        if comma >= 0 and not prefix[comma + 1 :].strip():
            return text[:comma] + text[end:]
        return prefix + text[end:]


class Documents:
    """Read, edit, and remove explicitly owned document slots."""

    @staticmethod
    def get(
        content: bytes | None, format_name: str, slot: tuple[str, ...]
    ) -> bytes | None:
        """Read a semantic slot or Markdown ownership block."""
        if content is None:
            return None
        text = content.decode()
        if format_name == "markdown":
            match = re.search(Documents._block_pattern(slot[0]), text, re.DOTALL)
            return str(match.group(1)).encode() if match else None
        data = Documents._parse(text, format_name)
        current: JsonValue = data
        for key in slot:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return Json.dumps(current).encode()

    @staticmethod
    def edit(
        content: bytes | None,
        format_name: str,
        slot: tuple[str, ...],
        value: bytes | None,
    ) -> bytes:
        """Preserve surrounding content while editing one slot."""
        text = content.decode() if content is not None else ""
        if format_name == "markdown":
            return Documents._markdown(text, slot[0], value).encode()
        Documents._parse(
            text or "{}", format_name
        ) if format_name != "toml" else Documents._parse(text, format_name)
        parsed = Json.loads(value.decode()) if value is not None else None
        if format_name == "toml":
            document = tomlkit.parse(text)
            # tomlkit mappings preserve comments; values have validated JSON boundaries.
            table = cast(MutableMapping[str, object], document)
            Documents._toml_set(table, slot, parsed, remove=value is None)
            return tomlkit.dumps(document).encode()
        result = JsoncEditor().replace(
            text or "{}\n", slot, parsed, remove=value is None
        )
        Documents._parse(result, format_name)
        return result.encode()

    @staticmethod
    def _parse(text: str, format_name: str) -> JsonObject:
        """Validate documents using independent native parsers."""
        try:
            data = (
                tomlkit.parse(text).unwrap()
                if format_name == "toml"
                else Json.loads(text)
                if format_name == "json"
                else json5.loads(text)
            )
            return Json.object(Json.value(data))
        except (ValueError, ParseError) as error:
            raise ConfigurationError("Invalid destination document") from error

    @staticmethod
    def _toml_set(
        table: MutableMapping[str, object],
        slot: tuple[str, ...],
        value: JsonValue,
        *,
        remove: bool,
    ) -> None:
        """Set nested TOML keys while retaining unrelated tables."""
        for key in slot[:-1]:
            if key not in table:
                if remove:
                    return
                table[key] = tomlkit.table()
            child = table[key]
            if not isinstance(child, MutableMapping):
                raise ConfigurationError(f"TOML slot parent is not a table: {key}")
            # tomlkit nested tables use string keys after parsing and slot validation.
            table = cast(MutableMapping[str, object], child)
        if remove:
            table.pop(slot[-1], None)
        else:
            table[slot[-1]] = value

    @staticmethod
    def _block_pattern(name: str) -> str:
        """Return the managed-block pattern."""
        marker = re.escape(name)
        return (
            rf"<!-- agentsync:{marker}:start -->\n(.*?)\n"
            rf"<!-- agentsync:{marker}:end -->"
        )

    @staticmethod
    def _markdown(text: str, name: str, value: bytes | None) -> str:
        """Replace or append an explicitly named managed block."""
        pattern = Documents._block_pattern(name)
        if value is None:
            return re.sub(pattern, "", text, flags=re.DOTALL)
        block = (
            f"<!-- agentsync:{name}:start -->\n{value.decode()}\n"
            f"<!-- agentsync:{name}:end -->"
        )
        if re.search(pattern, text, re.DOTALL):
            return re.sub(pattern, lambda _: block, text, flags=re.DOTALL)
        return text + ("\n" if text else "") + block + "\n"
