"""Regression tests for publishing metadata and repository safety boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.repository_checks import RepositoryChecks

from agentsync import __version__
from agentsync.exceptions import ConfigurationError


class TestRepositoryChecks:
    """Fail release checks when documentation or workflow controls regress."""

    def test_version_matches_tag(self, tmp_path: Path) -> None:
        """The same published version must identify runtime and tagged source."""
        file = tmp_path / "pyproject.toml"
        file.write_text(f'[project]\nversion = "{__version__}"\n', encoding="utf-8")
        checks = RepositoryChecks(tmp_path)
        assert checks.version(f"v{__version__}") == __version__
        with pytest.raises(ConfigurationError, match="tag"):
            checks.version("v99.99.99")
        file.write_text('[project]\nversion = "99.99.99"\n', encoding="utf-8")
        with pytest.raises(ConfigurationError, match="disagree"):
            checks.version()

    def test_documentation_link_boundaries(self, tmp_path: Path) -> None:
        """Local links must exist inside the repository; external URLs are untouched."""
        file = tmp_path / "README.md"
        file.write_text(
            "[external](https://example.invalid)\n[local](missing.md)", encoding="utf-8"
        )
        checks = RepositoryChecks(tmp_path)
        with pytest.raises(ConfigurationError, match="Broken"):
            checks.documentation()
        (tmp_path / "missing.md").write_text("# Present", encoding="utf-8")
        checks.documentation()
        file.write_text("[outside](../outside.md)", encoding="utf-8")
        with pytest.raises(ConfigurationError, match="Broken"):
            checks.documentation()

    @pytest.mark.parametrize(
        ("trigger", "permission", "action", "message"),
        [
            (
                "pull_request_target: {}",
                "contents: read",
                "actions/checkout@" + "a" * 40,
                "Privileged",
            ),
            ("pull_request: {}", "contents: read", "actions/checkout@main", "Unpinned"),
            (
                "pull_request: {}",
                "contents: write",
                "actions/checkout@" + "a" * 40,
                "read-only",
            ),
            (
                "pull_request: {}",
                "contents: read\n  id-token: write",
                "actions/checkout@" + "a" * 40,
                "read-only",
            ),
        ],
        ids=["privileged-trigger", "mutable-action", "write-default", "oidc-default"],
    )
    def test_workflow_controls(
        self, tmp_path: Path, trigger: str, permission: str, action: str, message: str
    ) -> None:
        """Untrusted PRs cannot gain workflow defaults intended only for publishing."""
        folder = tmp_path / ".github/workflows"
        folder.mkdir(parents=True)
        (folder / "check.yml").write_text(
            f"on:\n  {trigger}\npermissions:\n  {permission}\n"
            f"jobs:\n  test:\n    steps:\n      - uses: {action}\n",
            encoding="utf-8",
        )
        with pytest.raises(ConfigurationError, match=message):
            RepositoryChecks(tmp_path).workflows()
