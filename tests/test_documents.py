"""Independent structured parser and content-preservation scenarios."""

from __future__ import annotations

import json

import json5
import pytest
import tomlkit
from hypothesis import given
from hypothesis import strategies as st

from agentsync.documents import Documents
from agentsync.exceptions import ConfigurationError
from agentsync.jsonutil import Json


class TestDocuments:
    """Owned slots preserve unrelated document content."""

    @pytest.mark.parametrize(
        "format_name", ["json", "jsonc", "toml"], ids=["json", "jsonc", "toml"]
    )
    def test_nested_insert_update_remove(self, format_name: str) -> None:
        """Nested slots round-trip through independent parsers."""
        before = (
            b'# keep\n[other]\nvalue = "keep"\n'
            if format_name == "toml"
            else b'{"other":{"value":"keep"}}'
        )
        updated = Documents.edit(
            before, format_name, ("servers", "owned"), b'{"command":"tool"}'
        )
        owned = Documents.get(updated, format_name, ("servers", "owned"))
        assert owned is not None
        assert Json.loads(owned.decode()) == {"command": "tool"}
        changed = Documents.edit(
            updated, format_name, ("servers", "owned"), b'{"command":"new"}'
        )
        removed = Documents.edit(changed, format_name, ("servers", "owned"), None)
        assert Documents.get(removed, format_name, ("servers", "owned")) is None
        assert Documents.get(removed, format_name, ("other", "value")) == b'"keep"\n'

    def test_jsonc_comments_and_unrelated_formatting_preserved(self) -> None:
        """Token edits do not rewrite unrelated comments or values."""
        before = (
            b'{\n // retained\n "other" : [1, 2],\n "servers": {"old": {"com'
            b'mand": "old"}},\n}\n'
        )
        updated = Documents.edit(
            before, "jsonc", ("servers", "new"), b'{"command":"new"}'
        )
        assert b' // retained\n "other" : [1, 2],' in updated
        assert json5.loads(updated.decode())["servers"]["old"]["command"] == "old"

    @pytest.mark.parametrize(
        "before",
        [b"{}", b'{"a":1}', b'{"a":1,}', b"{\n// comment\n}"],
        ids=["empty", "member", "trailing", "comment"],
    )
    def test_insert_member_edge_cases(self, before: bytes) -> None:
        """Insertion preserves valid JSONC delimiters."""
        result = Documents.edit(before, "jsonc", ("b",), b"2")
        assert json5.loads(result.decode())["b"] == 2

    @pytest.mark.parametrize(
        "key", ["first", "middle", "last"], ids=["first", "middle", "last"]
    )
    def test_delete_json_members(self, key: str) -> None:
        """Deletion leaves strict JSON when the input was strict JSON."""
        before = b'{"first":1,"middle":2,"last":3}'
        result = Documents.edit(before, "json", (key,), None)
        assert key not in json.loads(result)

    def test_markdown_blocks_preserve_unrelated_text(self) -> None:
        """Only explicit markers are replaced or deleted."""
        first = Documents.edit(b"# User content\n", "markdown", ("rule",), b"first")
        assert Documents.get(first, "markdown", ("rule",)) == b"first"
        updated = Documents.edit(first, "markdown", ("rule",), b"new\\literal")
        assert Documents.get(updated, "markdown", ("rule",)) == b"new\\literal"
        assert Documents.edit(updated, "markdown", ("rule",), None).startswith(
            b"# User content\n"
        )

    @pytest.mark.parametrize(
        ("format_name", "before"),
        [("json", b"bad"), ("toml", b"[bad"), ("json", b'{"servers":3}')],
        ids=["invalid-json", "invalid-toml", "scalar-parent"],
    )
    def test_invalid_documents_block(self, format_name: str, before: bytes) -> None:
        """Malformed input or scalar parents cannot be silently replaced."""
        with pytest.raises(ConfigurationError):
            Documents.edit(before, format_name, ("servers", "name"), b"1")

    def test_absent_reads_and_deletions(self) -> None:
        """Missing slots remain absent without unrelated changes."""
        assert Documents.get(None, "json", ("x",)) is None
        assert Documents.get(b"{}", "json", ("x",)) is None
        assert Documents.get(b"text", "markdown", ("x",)) is None
        assert Documents.edit(b"{}", "json", ("x",), None) == b"{}"
        assert Documents.edit(b"", "toml", ("parent", "x"), None) == b""

    def test_toml_preserves_comments(self) -> None:
        """Unrelated TOML comments and table formatting survive merges."""
        before = b'# kept\n[other]\nvalue = "yes" # inline\n'
        updated = Documents.edit(
            before, "toml", ("mcp_servers", "tool"), b'{"command":"tool"}'
        )
        assert b"# kept" in updated
        assert b"# inline" in updated
        assert tomlkit.parse(updated.decode())["other"]["value"] == "yes"

    @given(
        value=st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=40)
    )
    def test_json_edit_idempotence_property(self, value: str) -> None:
        """Repeating semantic edits never accumulates content changes."""
        content = Json.dumps(value).encode()
        first = Documents.edit(b'{"other":true}', "json", ("owned",), content)
        assert Documents.edit(first, "json", ("owned",), content) == first
