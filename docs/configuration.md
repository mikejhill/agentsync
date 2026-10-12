# Configuration and report contract v1

The core validates orchestration. Extension-owned `options` remain open JSON objects. No mandatory universal customization schema is imposed.

| Field | Meaning |
|---|---|
| `version` | Envelope version; currently `1` |
| `sources` | Named objects: `location`, `provider` (`local`/`git`/entry point), `reader`, `style`, `select`, `options` |
| `destinations` | Named objects: concrete `location`, optional `profile` (generic when omitted), `scope` (`user`/`project`), `enabled`, `version`, `options` |
| `routes` | Unique `name`, source/destination lists, `select`, ordered `steps`, `allow_approximate`, `unsupported` (`block`/`exclude`) |
| `pipelines` | Named arrays expanded in place when their name appears in `steps` |
| `settings` | Positive `debounce`, `poll`, `verify`, and `remote_poll` seconds |

Relative paths resolve against the configuration file's directory. Tildes expand against the user's home. Selectors match `NAME` or `KIND/NAME` with shell glob syntax. Empty selections select nothing. Multiple selectors are ORed.

The transformation sequence is exactly route steps followed by destination `options.steps`. Named pipelines expand visibly in their position; nested named pipelines are rejected. Default routes contain explicit capability selections. There is no hidden post-conversion pipeline.

Built-in steps:

| `use` | `options` |
|---|---|
| `select`, `exclude` | `patterns`: selector array |
| `rename` | `names`: old name to new name |
| `prefix` | `add`, `remove`: strings |
| `replace` | `old`, `new`, optional `files` glob |
| `metadata` | `set`: object, `remove`: key array |
| `path-map` | `paths`: relative package path to new path |
| `split` | `names`: output identity array |
| `compose` | `name`, `kind` (defaults to instructions) |
| `format` | Explicit `kind` and/or `style` declaration after user-authored conversion |
| `executable` | `argv`: argument array, `timeout`: seconds (default 30) |

`format` declares the new contract; it does not rewrite hook payloads. A hook claiming a native style is validated structurally, but the user transformation remains responsible for executable behavior and payload compatibility.

Git source options: `ref` pins a branch, tag, or commit. Without `ref`, successful fetches follow the remote default branch. Source acquisition never trusts repository files as extension registrations.

Destination options: `renderer` selects an installed renderer; `steps` adds destination-specific transformations, including reusable named pipelines; `runtime_version` supplies a version for `version` constraint checks. Automatic runtime version detection is unavailable. `mcp_file` overrides the native MCP document for any profile. Claude user MCP otherwise uses the sibling `.claude.json`. VS Code `variant` defaults to `agent-host`; select `local` explicitly for Local prompt files and the older `servers` MCP schema. Project `.github` destinations place MCP in sibling `.mcp.json` (Agent Host) or `.vscode/mcp.json` (Local). User Agent Host destinations use `.copilot/mcp-config.json`.

## Versioning and migration

- Application version, configuration envelope version, report version, contract version, and extension API version are independent.
- Version `1` has no legacy migrations. Unknown configuration versions fail before writes.
- Future migrations must be explicit, preserve unknown namespaced options, stage a backup, and validate the migrated plan before replacing policy. No implicit destructive migration exists.
- Cache keys include input bytes/revisions, explicit pipelines, policy, destination, application version, extension API version, and contract version.

## Report v1

Sync/plan/status/explain return `version`, `config`, `applied`, `ok`, `sources`, `diagnostics`, and `targets`. Each target group contains `names`, `ok`, and either an actionable `error` or `operations` plus `outputs`. Operations contain `path` and `action` (`create`, `update`, `delete`). Outputs contain `path`, owned `slot`, and `provenance`.

Provenance records original source identities, rendered identity, harness contract/version, route, and ordered transformation names. Trusted plugins must preserve or combine input `origins` when constructing replacement customizations. `status` adds `last_run` for the selected configuration and the background `watcher` heartbeat. A missing heartbeat does not establish process liveness; a stale heartbeat indicates a stalled/stopped process requiring inspection.

Consumers must tolerate additional fields within the same envelope version. Error reports contain `version`, `ok: false`, and `error`. `contracts`, `service`, and `init` have command-specific envelopes, also versioned `1`.
