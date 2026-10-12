# Local implementation evidence

Date: 2026-10-11. Environment: Windows, Python 3.12.13.

| Gate | Result |
|---|---|
| `uv run poe check` | Passed: 235 tests; 94.05% branch-enabled coverage |
| Ruff formatting/linting | Passed; cyclomatic complexity maximum 10 |
| Strict `ty` | Passed; all rules configured as errors |
| `uv build` | Wheel and source distribution built |
| Safety mutation gate | All three mutants caught: deletion, unmanaged ownership, and approximation policy |
| Installed wheel CLI | Isolated bootstrap, validate, plan, sync, watch-once, status, explain, and contract inspection |
| Installed reconciliation | Add, update, delete, and managed drift repair checked against actual files |
| Real background watcher | Event/poll convergence, destination deletion repair, source deletion, and configuration reload tested in an isolated subprocess |
| Concurrent execution | Two real CLI processes serialized successfully against the same isolated configuration |
| Failure/recovery | Before-image rollback, interrupted journals, ownership write failures, rollback failures, and external-edit preservation tested |
| Performance smoke | Seven scenarios completed on a small corpus; measurements only, no approved baseline |

Machine-readable supporting files: `mutation.json`, `wheel-smoke.json`, and `benchmark-smoke.json`. The performance command returns nonzero without an approved baseline. That is intentional and is not reported as performance acceptance.

## Open release gates

- Native discovery, activation, precedence, reload behavior, and exact runtime versions for every supported harness surface.
- Native hook payload, exit-code, decision, and execution-environment evidence.
- Three-platform native service lifecycle validation. Current OS test/installation results are published under the repository's GitHub Actions runs; initial local evidence covered Windows only.
- Approved dedicated-runner baselines for the full 5,000-customization, 20,000-file, 250-MiB, six-target corpus.
- Additional native instrumentation for complete background idle CPU, peak memory, shared structured-document scaling, and service-lifecycle latency.

Conservative unsupported/approximate conversions remain explicit in the contract inventory. This is a working implementation, not a fully native-certified release. No user's real harness configuration or login startup integration was modified during development.
