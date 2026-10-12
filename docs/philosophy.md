# Philosophy

**SkillSinc distributes agent customizations. Users own distribution policy.**

A customization is a distributable unit of instructions, configuration, or behavior, including supporting files. Skills, instructions, agents, prompts, hooks, and MCP declarations are kinds. A harness is the application that discovers and executes them.

Priorities, in order: functional correctness, feature support, user experience, and harness compatibility.

- Keep authored sources authoritative. Restore managed destination drift, and propagate confirmed source deletions.
- Preserve unrelated content. Require explicit adoption of conflicting existing files or keys.
- Make conversion fidelity explicit. Equivalent, approximate, and unsupported are distinct outcomes.
- Provide mechanisms and a default recipe, without imposing a universal format or mandatory directory layout.
- Run manual, scheduled, and background distribution through one engine.
- Explain each output through source identity, route, transformations, contract, and ownership.
- Isolate harness policy from reconciliation. New kinds and integrations extend boundaries instead of rewriting deletion logic.

The expected experience is: initialize, author customizations, enable destinations, inspect a plan, sync, and optionally install login startup. Defaults never silently adopt existing harness content. A failed source read retains previously managed outputs.

Configuration is code-adjacent policy: make ordering visible, validate errors before writes, and require deliberate choices when an analogue changes activation or permissions.
