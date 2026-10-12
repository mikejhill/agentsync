# Security and repository controls

## Distribution boundaries

Treat transformation plugins as trusted code. Keep credentials as references, inspect public customization repositories, and do not relabel hooks without converting their behavioral protocol. Synchronization never executes distributed hook commands.

Ownership, complete scans, collision rejection, path checks, preconditions, and recovery constrain writes. These mechanisms cannot sandbox plugins or make unrelated processes transactional.

## Repository controls

- Protected `main`: pull requests, passing `CI` and `Security` checks, resolved conversations, linear history, and blocked deletion/force-push.
- CodeQL merge protection blocks error-level quality findings and high/critical security alerts.
- Solo-maintainer policy: zero mandatory approvals; CODEOWNERS requests review without requiring self-approval. Admin bypass is limited to pull requests on `main`.
- Release tags: updates and deletions blocked, with explicit maintainer/admin emergency bypass.
- Squash merging and automatic deletion of merged branches; merge commits and rebasing disabled.
- GitHub Actions tokens default to read-only; PR approval permission disabled.
- Actions restricted to required providers, and third-party actions pinned to commit SHAs.
- Dependabot, dependency alerts/security updates, CodeQL, private vulnerability reporting, and supported secret-scanning controls.
- Publishing isolated in the `pypi` environment, with maintainer approval and OIDC only in the publishing job.

See [releasing](releasing.md) for publisher identity. Never store PyPI API tokens in configuration, commits, or workflow logs. Repository settings are server-side controls; workflow YAML alone does not establish their enforcement. Record any host/account limitation instead of claiming a control is enabled.

GitHub-hosted runners handle untrusted PR checks. Dedicated self-hosted performance runners are manual-only and must not run unreviewed pull requests.
