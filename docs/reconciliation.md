# Reconciliation and recovery

## Ownership

SQLite under `$XDG_STATE_HOME/agentsync/` records owned files and named entries in shared documents. Unrelated entries and supported document formatting remain intact. An existing unmanaged path or key blocks a conflicting output, even when its content happens to match.

`agentsync adopt` explicitly enrolls collisions encountered in the desired plan. Inspect `plan` first and limit adoption with `--target`. Adoption follows the configured desired content; it is not an import of all existing destination content.

## Desired state and deletion

- Complete source snapshots establish desired outputs.
- Confirmed additions and updates are applied; managed destination edits and deletions are repaired.
- Confirmed source deletion or explicit route removal removes only owned outputs.
- Missing roots, incomplete scans, failed Git fetches, invalid documents, and incomplete submodule snapshots retain prior output.
- Identical shared outputs deduplicate. Conflicting files, document entries, case aliases, Unicode aliases, traversal, links, and source/output cycles block distribution.

Independent valid targets may proceed. Targets sharing a root or physical document form a conservative commit group. A blocked member blocks that group.

## Commit and recovery

1. Render and validate the group.
2. Compare desired state, current destination content, and ownership.
3. Recheck source revisions and destination preconditions.
4. Journal operations, before-images, and previous ownership.
5. Stage on the destination filesystem and atomically replace individual files.
6. Verify content, commit ownership, and remove the completed journal.

Failures roll back the affected group. Interrupted journals recover before new writes. A conflicting external edit during recovery blocks rather than overwriting ambiguous content; the journal remains available for diagnosis. Back up the journal and affected files before manual repair. Do not delete a journal to conceal an unresolved state.

Cooperating runs share a temporary lock directory and a state lock. Keep the login/scheduler temporary-directory environment consistent. Filesystem mutations by unrelated processes can still race portable path operations.

The guarantee is validated planning, atomic individual replacements, and recoverable groups. Multi-file or multi-target visibility is not simultaneous. Native harness reload behavior remains the harness's responsibility.
