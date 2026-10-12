# Usage

## Install

Requires Python 3.12+. Until a PyPI release is published:

```console
uv tool install git+https://github.com/mikejhill/skillsinc.git
```

After publication, use `uv tool install skillsinc`. Upgrade with `uv tool upgrade skillsinc`. The installed command and Python import are `skillsinc`.

## First distribution

```console
skillsinc init
skillsinc contracts list
```

Add a skill package under `~/.config/skillsinc/customizations/skills/review/SKILL.md`:

```markdown
---
name: review
description: Review code for correctness and maintainability.
---
Inspect the change, identify concrete defects, and explain their consequences.
```

Edit `~/.config/skillsinc/config.json`: enable the `shared` destination to distribute standard skills to `~/.agents/skills/`. Enable native destinations and routes for other kinds. Default templates remain disabled until selected.

```console
skillsinc validate
skillsinc plan
skillsinc sync
skillsinc status
skillsinc explain review
```

Use the [configuration example](config.example.json) as a recipe, not a universal format. Replace example repositories and source roots before running it. Missing sources intentionally block their dependent targets.

## Explicit configurations and schedulers

```console
skillsinc plan --config-file /absolute/path/config.json --target shared --json
skillsinc sync --config-file /absolute/path/config.json --json
```

Options follow the command. On Windows, quote paths containing spaces, for example `skillsinc sync --config-file "C:\Users\Mike\My Config\config.json"`.

Use an absolute installed executable path from AHK, Task Scheduler, cron, or another scheduler. Explicit missing configurations fail without bootstrapping defaults. Exit codes: `0` success, `1` blocked/operational failure, `2` usage/configuration failure, and `130` interruption. Check individual target results when the overall run fails.

## Background operation

```console
skillsinc watch
skillsinc service install
skillsinc service start
skillsinc service status
```

Service installation is explicit. See [operations](operations.md) for platform behavior and [reconciliation](reconciliation.md) before using `adopt`.
