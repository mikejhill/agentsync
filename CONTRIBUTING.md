# Contributing

1. Read [philosophy](docs/philosophy.md), [design](docs/design.md), and [architecture](docs/architecture.md).
2. Create a branch and keep changes scoped. Preserve unrelated harness configuration.
3. Run `uv sync --locked`, then `uv run poe check`.
4. Include failure-path tests for ownership, deletion, recovery, or conversion-policy changes.
5. Open a pull request describing the behavior, validation, and fidelity impact.

Use Python 3.12+, the `src/skillsinc/` layout, immutable value objects, typed class-based services, Ruff, and strict `ty`. Commit `uv.lock`. Do not weaken checks to obtain a passing build.

Harness changes require independent fixtures, vendor documentation, a verification date, and explicit unsupported/approximate behavior. Native smoke evidence must identify runtime version and scope. Ordinary tests use isolated homes and never install real login services.

Report defects through the issue forms. Report security defects privately through [GitHub Security Advisories](https://github.com/mikejhill/skillsinc/security/advisories/new). Maintainers use the [release process](docs/releasing.md).
