# Roadmap and release evidence

The alpha implementation supplies distribution mechanisms and conservative format contracts. Prioritize correctness before broader conversion support.

Remaining native acceptance:

1. Record exact harness runtime versions, discovery, activation, precedence, and reload behavior for every declared surface/scope.
2. Validate native hook input/output, exit-code decisions, and execution environments.
3. Exercise actual login-service installation, start, stop, uninstall, and convergence on all three platforms.
4. Approve full-corpus performance baselines on dedicated runners: 5,000 customizations, 20,000 files, 250 MiB, and six targets.
5. Instrument complete background idle CPU, peak memory, shared structured-document scaling, and service-lifecycle latency.

Fixture tests and CI installation checks are evidence for their own boundaries. They do not mark native behavior verified. See [contracts](contracts.md), [testing](testing.md), and [local evidence](../evidence/VALIDATION.md).
