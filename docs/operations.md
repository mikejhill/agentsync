# Operations

## Watching

`watch` performs an initial sync, subscribes to source/configuration/destination events, and periodically reconciles missed changes. Defaults: 500-ms debounce, 60-second local poll, five-minute full verification, five-minute Git poll, and bounded retry backoff.

Temporarily invalid configuration retains the last valid policy. Failed sources retain output. Generated internal writes are filtered to avoid feedback loops. Polling remains available when event subscriptions fail.

## Login startup

| Platform | Integration |
|---|---|
| Windows | Hidden per-user Task Scheduler task |
| Linux | systemd user service; desktop autostart fallback |
| macOS | Per-user LaunchAgent |

```console
skillsinc service install --config-file /absolute/path/config.json
skillsinc service start --config-file /absolute/path/config.json
skillsinc service status --config-file /absolute/path/config.json
skillsinc service stop --config-file /absolute/path/config.json
skillsinc service uninstall --config-file /absolute/path/config.json
```

Installation stores absolute executable/configuration paths and installation-time XDG roots. Reinstall after moving the installed runtime or changing those roots. Desktop autostart starts at next login; use foreground `watch` for immediate execution. Uninstall retains customizations and configuration.

## Diagnostics

| Symptom | Action |
|---|---|
| Unmanaged collision | Inspect `plan`; reroute or explicitly adopt the affected target |
| Approximate conversion blocked | Map the semantics explicitly or allow approximation on that route |
| Source unavailable/stale | Restore the source or network access, then sync |
| Recovery blocked | Preserve the journal and files; reconcile the reported external edit before retrying |
| No background progress | Inspect service status, watcher heartbeat, and `$XDG_STATE_HOME/skillsinc/watch.log` |
| Customization undiscovered | Verify native location, scope, runtime version, trust, and reload requirements |

`status --json` separates current drift, last distribution results, and watcher heartbeat. A recent heartbeat alone does not prove native harness discovery. Native service lifecycle evidence remains a distinct release gate.
