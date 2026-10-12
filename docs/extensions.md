# Extension API v1

Constructor injection and structural protocols are defined in `agentsync.models`. Extensions are installed trusted Python code. They cannot be declared by downloaded repositories.

| Python entry-point group | Constructor | Protocol |
|---|---|---|
| `agentsync.sources` | `(Source, cache_root)` | `snapshot() -> Snapshot` |
| `agentsync.readers` | `()` | `read(snapshot, source_name, style) -> tuple[Customization, ...]` |
| `agentsync.transformations` | `()` | `apply(items, options) -> tuple[Customization, ...]` |
| `agentsync.renderers` | `(Destination)` | `render(item) -> tuple[Output, ...]` |

Transformations may filter, split, or compose packages. Preserve `source`, `origins`, `style`, metadata, file contents, and permissions unless the configured transformation intentionally changes them. `origins` tracks original source identities through renaming and composition. Renderers return complete files or structured slots; they never write destinations. New kinds/providers/renderers require no reconciliation changes.

Register a transformation:

```toml
[project.entry-points."agentsync.transformations"]
my-transform = "my_package:MyTransformation"
```

Configure it through `{"use":"my-transform","options":{"vendor.namespace":{}}}`. The implementation validates its own options.

## Executable protocol v1

Configure `{"use":"executable","options":{"argv":["/absolute/program","arg"],"timeout":30}}`. No shell is used. Stdout is bounded to 4 MiB; excess output terminates the subprocess. Stderr is discarded to avoid exposing plugin secrets. Timeout/failure blocks the target.

Stdin and stdout use the same envelope:

```json
{
  "version": 1,
  "workspace": "/temporary/staging",
  "customizations": [
    {
      "name": "review",
      "kind": "skills",
      "style": "portable",
      "source": "personal",
      "origins": ["personal:skills/review"],
      "metadata": {"description": "Review code"},
      "package": "/temporary/staging/0"
    }
  ]
}
```

Packages contain staged files. A plugin may edit those files and return zero-to-many records. Returned packages must remain within staging and contain regular files; traversal and links are rejected. The process may access anything its user account can access: containment checks protect proposed outputs, not the host from trusted executable code.

Native conversion plugins should produce documented native metadata and payloads and declare the resulting `style`. Cross-harness hook behavior is never inferred from event spelling. Include independent fixtures and behavioral tests with every extension release.
