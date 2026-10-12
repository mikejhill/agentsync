# Usage

## Install

Requires Python 3.12+. Until a PyPI release is published:

```console
uv tool install git+https://github.com/mikejhill/agentsync.git
```

After publication, use `uv tool install agentsync-customizations`. Upgrade with `uv tool upgrade agentsync-customizations`. The installed command and Python import are `agentsync`.

## First distribution

```console
agentsync init
agentsync contracts list
```

Add a skill package under `~/.config/agentsync/customizations/skills/review/SKILL.md`:

```markdown
---
name: review
description: Review code for correctness and maintainability.
---
Inspect the change, identify concrete defects, and explain their consequences.
```

Edit `~/.config/agentsync/config.json`: enable the `shared` destination to distribute standard skills to `~/.agents/skills/`. Enable native destinations and routes for other kinds. Default templates remain disabled until selected.

```console
agentsync validate
agentsync plan
agentsync sync
agentsync status
agentsync explain review
```

Use the [configuration example](config.example.json) as a recipe, not a universal format. Replace example repositories and source roots before running it. Missing sources intentionally block their dependent targets.

## Explicit configurations and schedulers

```console
agentsync plan --config-file /absolute/path/config.json --target shared --json
agentsync sync --config-file /absolute/path/config.json --json
```

Options follow the command. On Windows, quote paths containing spaces, for example `agentsync sync --config-file "C:\Users\Mike\My Config\config.json"`.

Use an absolute installed executable path from AHK, Task Scheduler, cron, or another scheduler. Explicit missing configurations fail without bootstrapping defaults. Exit codes: `0` success, `1` blocked/operational failure, `2` usage/configuration failure, and `130` interruption. Check individual target results when the overall run fails.

## Background operation

```console
agentsync watch
agentsync service install
agentsync service start
agentsync service status
```

Service installation is explicit. See [operations](operations.md) for platform behavior and [reconciliation](reconciliation.md) before using `adopt`.
