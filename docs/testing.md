# Quality and release gates

## Deterministic local gate

```console
uv run poe check
```

Runs Ruff format/lint (complexity <=10), strict `ty` (all rules are errors), and pytest with branch-enabled coverage >=90%. Tests isolate HOME, USERPROFILE, and all XDG roots. Real local Git repositories and executable plugins use temporary directories without credentials. Native services are generated/tested with fake process boundaries; ordinary tests never install login startup or touch real harness configuration.

Coverage includes configuration/bootstrap, ordered pipelines, binary package files, independent contract expectations, many-to-many routing, shared targets, generic/custom kinds, JSONC comments, unrelated document content, adoption, deletion, source failures, drift, rollback, interrupted journals, external edits, CLI exits/help/JSON, virtual-time watching, native service definitions, and plugins.

Property tests verify deterministic edits and unrelated-content preservation. Add failure-path tests whenever ownership, recovery, or conversion policy changes.

## Mutation gate

```console
uv run python -m tests.quality_tools mutation --output mutation.json
```

Copies sources/tests into temporary directories and mutates deletion, unmanaged-ownership, and approximation decisions. Only actual assertion failures count as killed mutants; collection/internal errors fail the gate. The original checkout is never modified.

## Performance gate

```console
uv run python -m tests.quality_tools benchmark --baseline baselines/PLATFORM.json --output performance.json
```

Dedicated runners use exactly 5,000 skills, 20,000 files, 250 MiB, and six targets. Five repetitions measure cold distribution, warm no-op, one-file edits, bursts, deletion batches, shared-target distribution, and watcher timer-loop idle CPU. A regression fails when the mean worsens >20% and conservative 95% confidence intervals separate. Corpus/platform mismatch or missing approval fails the release comparison. Approve stable hardware/OS/runtime baselines explicitly; never generate an automatic passing baseline from the implementation under test.

`--quick` uses a smaller corpus to validate benchmark mechanics. It is not performance acceptance evidence. Watcher timer-loop CPU excludes OS event subscriptions. Full background process idle CPU, peak memory, shared structured-document scaling, and service-lifecycle latency require dedicated native instrumentation before release acceptance.

## CI and installation

The correctness workflow runs Windows, macOS, and Linux on Python 3.12, 3.13, and 3.14. It runs the complete local gate, checks documentation links/configuration examples, validates SHA-pinned workflow actions, builds and validates wheel/sdist metadata, checks package data/license contents, and installs the wheel into isolated homes on all three platforms. Installed tests verify bootstrap, read-only planning, add/update/delete convergence, drift repair, status, explanation, and packaged contract data. Mutation runs separately within CI.

Security CI audits the locked runtime/development dependencies and runs Python CodeQL security/quality queries. `CI` and `Security` aggregate jobs fail if any required component fails. Workflows upload JUnit, coverage, installed-CLI, mutation, and audit artifacts. [GitHub Actions](https://github.com/mikejhill/skillsinc/actions) is the source for current remote results; platform fixtures are not equivalent to OS execution.

`uv run poe workflow-check` uses the pinned actionlint Go module and the dedicated runner labels declared in `pyproject.toml`. Locally, a checksum-verified actionlint executable can be supplied with `uv run python -m tests.workflow_checks --executable /path/to/actionlint`. The repository checks in `uv run poe check` validate workflow pins and permission defaults without network access.

The performance workflow is manual-only on reviewed `main` and requires an approved baseline on a dedicated self-hosted runner. Release CI reuses correctness and security workflows on the tagged source before OIDC publishing. See [release controls](releasing.md) and [repository security](security.md).

## Native/runtime and release checklist

- [ ] Windows/macOS/Linux CI and wheel installation evidence.
- [ ] Native discovery/activation for every supported surface and declared scope.
- [ ] Runtime versions and vendor precedence/reload requirements recorded.
- [ ] Native hook I/O/exit/decision behavior, rather than event-name substitution.
- [ ] Real per-user service install/start/stop/uninstall on all platforms.
- [ ] Background missed-event, Git-fetch, and configuration-reload convergence.
- [ ] Process interruption and crash recovery, including rollback failures and locked files.
- [ ] Approved fixed-corpus performance baselines, idle CPU, memory, and shared-document scaling.
- [ ] Mutation gate and deterministic >=90% branch-enabled coverage.

Release acceptance stays open until these external/native checks are evidenced. The package is a working implementation with explicit conservative conversion limits; it is not labeled a fully native-certified release.
