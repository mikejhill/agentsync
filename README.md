# SkillSinc

[![CI](https://github.com/mikejhill/skillsinc/actions/workflows/ci.yml/badge.svg)](https://github.com/mikejhill/skillsinc/actions/workflows/ci.yml)
[![Security](https://github.com/mikejhill/skillsinc/actions/workflows/security.yml/badge.svg)](https://github.com/mikejhill/skillsinc/actions/workflows/security.yml)

Distribute **agent customizations**—skills, instructions, agents, prompts, hooks, MCP declarations, and supporting files—from user-defined sources into harness-compatible destinations.

SkillSinc supplies the mechanism. Your configuration defines distribution policy.

- Many-to-many routes, ordered transformations, and Python/executable plugins.
- Local and Git sources; manual CLI, external schedulers, and event/poll watching.
- Source-authoritative drift repair with explicit ownership, deletion boundaries, and journaled recovery.
- Entry-preserving JSON, JSONC, TOML, and Markdown edits.
- Explicit equivalent, approximate, and unsupported conversion outcomes.
- XDG storage on Windows, macOS, and Linux; native harness paths remain native.

## Start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). Git sources also require Git. Until PyPI publication:

```console
uv tool install git+https://github.com/mikejhill/skillsinc.git
skillsinc init
```

1. Add packages under `~/.config/skillsinc/customizations/`.
2. Enable destinations and edit routes in `~/.config/skillsinc/config.json`.
3. Preview and apply:

```console
skillsinc validate
skillsinc plan
skillsinc sync
skillsinc explain review
skillsinc watch
```

Default destinations are disabled. Existing harness content is never silently imported or adopted. Failed source acquisition retains managed output. See [usage](docs/usage.md) and [configuration](docs/configuration.md). The package, command, and Python import are all `skillsinc`.

## Harness coverage

Profiles cover Claude Code, Codex CLI/desktop, Copilot CLI/VS Code, Cursor IDE/CLI, Gemini CLI, OpenCode, shared `.agents` skills, and generic directories. Conversion support varies by kind, scope, and semantics. Unapproved losses block distribution.

**Alpha:** passing fixtures do not prove native discovery or behavior. Native versions, hook behavior, actual service lifecycle, and approved performance baselines remain separate [release gates](docs/roadmap.md). See the [contract inventory](docs/contracts.md).

## Develop and release

```console
uv sync --locked
uv run poe check
uv build
uv run poe package-check
```

CI runs Python 3.12–3.14 on Windows, macOS, and Linux, installed-wheel tests, mutation checks, documentation/workflow checks, dependency audits, and CodeQL. Releases rerun checks on the tag and use approval-gated PyPI Trusted Publishing.

[Documentation](docs/README.md) · [Philosophy](docs/philosophy.md) · [Design](docs/design.md) · [Architecture](docs/architecture.md) · [Contributing](CONTRIBUTING.md) · [Release process](docs/releasing.md) · [Security](SECURITY.md) · [Changelog](CHANGELOG.md)

MIT licensed. Plugins are trusted code; distributing hooks does not execute them.
