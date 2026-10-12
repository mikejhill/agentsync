# Security policy

During the alpha period, security fixes target `main` and the latest published release. Earlier releases receive no separate maintenance guarantee.

Report suspected traversal, unintended deletion, ownership violations, executable injection, credential exposure, or publishing compromise through [private vulnerability reporting](https://github.com/mikejhill/skillsinc/security/advisories/new). Include a minimal reproduction, affected version, operating system, and expected boundary. Do not include real credentials or post exploit details in public issues before coordination.

Plugins are trusted executable code. Source repositories cannot register plugins implicitly, and synchronization does not execute distributed hooks. Destination containment protects distribution boundaries; it does not sandbox user-configured plugins.

See [security and repository controls](docs/security.md) for controls and operational assumptions. Response timing is best effort; no unsupported service-level commitment is implied.
