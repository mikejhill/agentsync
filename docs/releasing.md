# Release process

## One-time publisher setup

Register a pending publisher in the owning PyPI account before uploading the first package:

| Field | Production | Test index |
|---|---|---|
| Project | `agentsync` | `agentsync` |
| GitHub owner | `mikejhill` | `mikejhill` |
| Repository | `agentsync` | `agentsync` |
| Workflow | `release.yml` | `release.yml` |
| Environment | `pypi` | `testpypi` |
| Registration | [PyPI account publishing](https://pypi.org/manage/account/publishing/) | [TestPyPI account publishing](https://test.pypi.org/manage/account/publishing/) |

After registration, set the corresponding GitHub environment variable `PYPI_PUBLISH_ENABLED=true`. Environments require maintainer approval. Names must match exactly. A pending publisher does not reserve a project name; recheck before first release. See [PyPI's instructions](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).

The workflow uses OIDC and attestations. No long-lived PyPI token is required. Repository publication does not upload a package; the publisher gate remains disabled until registration is complete.

## Prepare

1. Open a release PR. Match versions in `pyproject.toml` and `src/agentsync/__init__.py`; CLI version derives from the latter.
2. Run `uv lock`, date the changelog, and document conversion losses and open native gates.
3. Run `uv run poe check`, `uv build`, `uv run poe package-check`, and `uv run python -m tests.repository_checks --dist dist`.
4. Require green `CI` and `Security`. Review three-platform installed-CLI artifacts, mutations, and native/performance evidence. Record alpha-only limitations without marking unverified behavior verified.
5. Merge into protected `main`. Create `vVERSION` on that commit. Release checks require the tag version to match metadata and the tagged commit to be reachable from `main`.

For the initial release, the existing version `0.1.0` may remain unchanged. Replace `Unreleased` with a dated changelog section before tagging.

## Test and publish

```console
git fetch origin
git tag -a v0.1.0 origin/main -m "AgentSync 0.1.0"
git push origin v0.1.0
gh workflow run release.yml --ref main -f tag=v0.1.0 -f index=testpypi
```

Approve `testpypi`, inspect artifacts/attestations, and test installation with an explicit package pin. TestPyPI may lack dependencies; inspect the built wheel and install its runtime dependencies from normal PyPI in an isolated environment before installing the TestPyPI package. Never silently change production index precedence.

Create release notes listing changes, fidelity limits, migration needs, and evidence, then publish a GitHub release:

```console
gh release create v0.1.0 --verify-tag --title "AgentSync 0.1.0" --notes-file release-notes.md
```

The release event reruns CI and security on the tag, verifies version/main ancestry, builds distributions, and awaits `pypi` approval. The publishing job receives artifacts and OIDC permission without checking out source or running tests. After PyPI succeeds, a separate job attaches those same artifacts to the GitHub release.

## Verify and recover

- Confirm the exact PyPI version, wheel/sdist metadata, attestations, installed CLI, and GitHub asset hashes.
- Published versions are immutable. Do not replace a version or rewrite its tag.
- If PyPI succeeds but asset attachment fails, upload existing workflow artifacts manually; do not retry the PyPI upload.
- If publication fails before upload, correct publisher identity, environment approval, or project ownership, then rerun only the failed job.
- Yank a defective release when appropriate, and publish a new corrective version. Handle vulnerabilities through private advisories.

SHA-pinned actions receive Dependabot update PRs. Routine CI and build jobs have no publishing permission.
