# Private storage

Keep personal state outside the repository and installed skill folders.
The local configuration pointer defaults to `~/.daily-brief/config.json`.
`DAILY_BRIEF_CONFIG` can select a different private pointer file.
The pointer contains only the chosen data directory.
Do not copy the pointer into a shared repository.

The data directory contains:

- `reference.md`: confirmed standing facts, source dates, review dates, and deferred sections.
- `tools.json`: account aliases, permitted scopes, access checks, and manual fallbacks.
- `setup.json`: readiness, completed areas, deferred questions, and the next setup question.
- `database.json`: dated commitments, observed outcomes, candidate patterns, and run snapshots.
- `reports/`, `notes/`, and `backups/`: private outputs and preserved versions.

## Commands

Run the helper from the daily-brief folder, or use the absolute script path.

```sh
python scripts/state.py status
python scripts/state.py init --data-dir /absolute/private/folder
python scripts/state.py read --file reference.md
python scripts/state.py write --file reference.md --input /private/draft.md --expected-sha HASH
python scripts/state.py read --file tools.json
python scripts/state.py put --collection runs --id RUN_ID --input /private/run.json --expected-revision 0
```

`read` returns content and its SHA-256 hash.
For `write`, merge existing content and pass that hash to reject stale edits.
For `put`, read `database.json` and pass its current revision.
Use one writer per data directory; a local lock does not coordinate multiple computers through cloud sync.
If conflicting cloud copies appear, stop writes and reconcile with the user.
Never remove a lock automatically; establish that no other writer is active before recovering a stale lock.
The helper makes backups and uses atomic replacement.
A local write does not verify remote cloud upload.

Keep routine authority in `reference.md` and dated exceptions in commitments.
Use stable source IDs or UUIDs for records, and preserve earlier snapshots in backups.
Each run records target date, timezone, status, reference hash, source gaps, priorities, timeblocks, dependencies, meeting agendas, lookahead, and report paths.
Track interview completion separately from report certainty: an interview can finish with a draft report.
Keep source exports and credential files out of all shared examples and releases.

## Interview history

Use `scripts/memory.py` for append-only questions, answers, decisions, and linked task updates.
Read [interview-memory.md](interview-memory.md) for migration, invocation counting, and twentieth-run reviews.
Keep the complete history in the private database; never publish it with the package.
