# Design

## Scope

Distribute local or Git customization packages to concrete filesystem destinations. Convert formats through configurable pipelines and conservative harness contracts. Support source-authoritative reconciliation, manual CLI runs, external schedulers, watching, and optional login integration.

Cloud account configuration, organization administration, harness process control, and plugin sandboxing are outside the initial scope. Sharing a field name does not establish semantic equivalence.

## Decisions

| Decision | Reason |
|---|---|
| Versioned JSON orchestration envelope | Named sources, destinations, and routes remain inspectable; extension options stay open |
| Optional harness profile | Generic distribution works without native conversion |
| Typed packages with retained metadata and origins | Preserve native-only fields and trace identities through transformations |
| Ordered collection transformations | Filtering, renaming, splitting, and composition need zero-to-many behavior |
| SQLite ownership outside destination content | Whole files and document entries need explicit, durable ownership |
| Combined planning before writes | Shared destinations must deduplicate identical outputs and reject conflicts |
| Recoverable commit groups | Individual replacements can be atomic; multi-file visibility cannot be guaranteed |
| Explicit approximation/exclusion | Activation, permissions, models, and hook behavior cannot be guessed safely |
| Events plus polling | Missed events, Git updates, and temporary failures must converge |
| Separate native evidence | Renderer fixtures cannot prove runtime discovery or behavior |

## Configuration and lifecycle

Bootstrap only default `init`, `sync`, and `watch`. Explicit missing configurations fail. Read-only commands never create default sources. Honor absolute XDG overrides on every OS, while native harness discovery paths remain native.

Routes combine source snapshots, select packages, apply route steps and destination steps in order, then render. A target blocks on invalid or unapproved lossy conversion. Targets sharing a physical document commit together; independent targets can proceed.

Contract/API/configuration/report versions are independent of the package version. Changes to discovery or semantics require a contract update and fixtures. See [configuration](configuration.md), [contracts](contracts.md), and [reconciliation](reconciliation.md).
