# Harness contract inventory v1

Evidence date: 2026-10-11. The registry distinguishes format fixtures from native execution. All built-in profiles currently report `native_verified: false` and an empty tested-runtime-version list. User-supplied `runtime_version` checks a constraint; it does not establish verified behavior.

## Discovery and fidelity

Treat `location` as the appropriate native customization directory unless the table calls for a project root. An explicit `options.mcp_file` can select a different native MCP document while preserving named-entry ownership.

| Surface | Instructions | Skills | Agents/prompts | MCP and hooks |
|---|---|---|---|---|
| Claude Code | `CLAUDE.md`; scoped `rules/*.md` with `paths` | `skills/*/SKILL.md` | `agents/*.md`; `commands/*.md` | User sibling `.claude.json`; project `.mcp.json`; native grouped hooks in `settings.json` |
| Codex CLI | `AGENTS.md` under native config/project scope; path-scoped conversion needs opt-in | Route to shared `.agents` explicitly | `agents/*.toml`; `prompts/*.md` | `config.toml` `mcp_servers`; grouped `hooks.json` |
| Codex desktop | Same filesystem contract as CLI; runtime verification separate | Shared `.agents` | TOML agent definitions; prompt discovery requires native evidence | Same native config layer; never changes cloud settings |
| Copilot CLI | Native `copilot-instructions.md`; scoped `instructions/*.instructions.md` | Native `skills/` or shared `.agents` | Markdown `agents/`; standalone prompts unsupported by this profile | `mcp-config.json`; owned `hooks/skillsinc-NAME.json` |
| VS Code Copilot | User `.copilot/copilot-instructions.md` and `instructions/`; project `.github/copilot-instructions.md` and `instructions/` | Native Copilot skills or shared skills | Native agent files; prompt files require `options.variant: local` | Agent Host user `mcp-config.json`, project root `.mcp.json`; Local `mcp.json` with `servers`; native hook files |
| Cursor IDE | Project `AGENTS.md` and `.cursor/rules/*.mdc` | `.cursor/skills/` or shared skills | Native `agents/` and `commands/` formats | `mcp.json`; `hooks.json` with schema version and native lower-camel events |
| Cursor CLI | Profile tracked separately; native discovery requires smoke evidence | Native/shared skills | Basic formats only; invocation differences need explicit mapping | Native MCP/hook declarations; no guessed event substitutions |
| Gemini CLI | `GEMINI.md` | `skills/*/SKILL.md` | Agents unsupported; `commands/*.toml` with `prompt` and `description` | `settings.json`; grouped hooks and Gemini event names |
| OpenCode | `AGENTS.md` | `skills/*/SKILL.md` | `agents/*.md`, `commands/*.md` | `opencode.jsonc` `mcp`; hooks require a plugin adapter |
| Shared `.agents` | User-global instructions unsupported; project-root `AGENTS.md` allowed | Standard skill packages | Agents/prompts/hooks/MCP lack a shared discovery contract | Use native targets or installed renderer |
| Generic | No activation semantics assumed | Whole package preservation | Any customization kind is copied | No native config conversion |

Project/native discovery roots differ across kinds. Cursor project `AGENTS.md` belongs at the project root, while `.cursor` owns rules, commands, and MCP files. VS Code defaults to Agent Host's portable Copilot layout. For a project `.github` destination, MCP is written to its sibling project-root `.mcp.json`. With `options.variant: local`, MCP uses sibling `.vscode/mcp.json`, and project prompt files are permitted. User Local MCP requires an explicit profile-native location or `options.mcp_file`; user prompt discovery remains blocked. No prompt files are written for Agent Host sessions without an explicit custom conversion.

Native documentation:

- [Claude skills](https://code.claude.com/docs/en/skills), [memory/rules](https://code.claude.com/docs/en/memory), and [hooks](https://code.claude.com/docs/en/hooks).
- [Codex configuration](https://developers.openai.com/codex/config-reference), [subagents](https://developers.openai.com/codex/multi-agent), and [hooks](https://learn.chatgpt.com/docs/hooks).
- [Copilot CLI instructions](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions), [agent schema](https://docs.github.com/en/copilot/reference/custom-agents-configuration), and [hooks](https://docs.github.com/en/copilot/reference/hooks-reference).
- [VS Code agents](https://code.visualstudio.com/docs/agent-customization/custom-agents), [session migration](https://code.visualstudio.com/docs/agent-customization/migrate-customizations), [instructions](https://code.visualstudio.com/docs/agent-customization/custom-instructions), and [MCP configuration](https://code.visualstudio.com/docs/agent-customization/mcp-servers).
- [Cursor rules](https://cursor.com/docs/rules), [skills](https://cursor.com/docs/skills), and [hooks](https://cursor.com/docs/hooks).
- [Gemini configuration](https://geminicli.com/docs/reference/configuration/) and [hooks](https://geminicli.com/docs/hooks/).
- [OpenCode configuration](https://opencode.ai/docs/config/), [agents](https://opencode.ai/docs/agents/), and [commands](https://opencode.ai/docs/commands/).
- [Agent Skills specification](https://agentskills.io/specification) and [AGENTS.md](https://agents.md/).

## Conversion decisions

| Semantic feature | Default decision |
|---|---|
| Standard skill body, metadata, and relative files | Equivalent for supported skill discovery paths |
| Native activation fields exported to another family | Approximate; explicit permission required |
| Native instruction agent exclusions or task-relevance activation | Block unless an explicit mapping or approximation policy allows loss |
| Copilot `applyTo` to Claude `paths` | Basic path-list equivalent; glob dialect differences need native evidence |
| Path-scoped instruction to a profile without matching | Approximate conditional guidance in its global instruction document |
| Basic agent description/body | Equivalent representation; native invocation remains unverified |
| Native agent tools/permissions | Block unless mapped explicitly or approximation permits dropping fields |
| Claude `$ARGUMENTS` to Gemini `{{args}}` | Basic argument-list substitution |
| Claude arguments to VS Code interactive inputs | Approximate; explicit permission required |
| Native prompt invocation metadata | Block/approximate across families; do not assume activation equivalence |
| Standard stdio/HTTP MCP declaration | Named-slot conversion; OpenCode command-array/environment and Codex HTTP-header fields are mapped |
| Hook executable payload/decision semantics | Native pass-through only; cross-family conversion requires an explicit transformation |
| Shared configuration with existing unrelated keys | Preserve unrelated keys; unmanaged colliding owned entries block |

Model identifiers, tool names, allowlists, permission modes, MCP authentication, hook decisions, and native activation options are not interchangeable simply because their YAML/JSON fields have similar names. Supply explicit transformations for those semantics.

## Hook behavior

Hooks remain inert during distribution. Their originating harness determines input fields, decision payloads, exit-code behavior, shell/environment, matcher semantics, and timing. `HookPolicy` validates supported native event names and structural command/prompt/HTTP declarations; it does not prove that an executable implements the wire protocol correctly.

- Claude/Codex/Gemini handlers use grouped `hooks` arrays; events and decisions remain native.
- Cursor's lower-camel event names and per-script records remain intact; schema version is owned separately.
- Copilot hook files are owned as complete generated files under the native hooks directory, preserving other hook files.
- OpenCode hook behavior requires a plugin implementation.
- A transformation that relabels native style must also adapt executable behavior. Relabeling alone is insufficient.

## Precedence, reload, and native evidence

SkillSinc writes only the configured native layer. It does not override vendor precedence, project trust, organization policy, feature flags, or remote/cloud customization discovery. Vendor precedence and discovery settings must be tested in the actual selected runtime before approving a release.

Use fresh harness sessions after distribution for native discovery tests. Confirm skill/agent/prompt presence, scoped instruction activation, MCP transport startup, and hook payload/decision behavior independently. Record exact runtime versions, OS, profile, scope, command, result, and reload requirements. Update the contract version and fixtures when vendor semantics change.

Current contract limitations are deliberately visible. Fixture passing alone cannot close the native-discovery release gate.
