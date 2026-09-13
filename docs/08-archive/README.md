# Archive

> Status: archived
> Date: 2026-09-14
> Replaced by: active documents in [`docs/`](../README.md)

Superseded, retired, and historical documents kept for context. Nothing in
this directory is a current task queue or implementation contract.

## Start here

- [Archived audits](audit/) — point-in-time reviews and risk reports.
- [Archived insights](insight/) — maintainer execution history, with a
  consolidated [execution index](insight/EXECUTION-INDEX.md) and
  [finding ledger](insight/LEDGER.md).
- [Archived superpowers](superpowers/) — retired plans and design specs.
- [Code review (2026-06-15)](code-review-2026-06-15.md) — standalone historical
  review.

For current behavior, follow the links from the root [documentation index](../README.md)
and the project [README](../../README.md). When an archived document conflicts
with active code or documentation, the active source wins.

## Contents

| Document | Description |
| -------- | ----------- |
| [audit/](audit/) | Point-in-time audit reports (cross-validation, prioritized findings, resource lifecycle) |
| [insight/](insight/) | Round-based SPEC/PLAN/TASK records, deep-insight reports, execution index, and ledger |
| [superpowers/](superpowers/) | Historical implementation plans and design specs |
| [Devil's Critic Code Review 2026-06-15](code-review-2026-06-15.md) | Round-81 full-codebase critical review |

Move documents here when they no longer reflect current practice. Add a short
note in the document (or its section README) naming the replacement and date
of archival. Active ADRs and RFCs stay in place and are marked superseded
rather than moved.

## Archive conventions

- Preserve historical filenames and content; index or annotate rather than
  rewriting history.
- Keep a metadata block directly below each title when adding a new archive
  index entry: `Status: archived`, `Date: YYYY-MM-DD`, and `Replaced by:`.
- `_template.md` files are scaffolds, not archival records.
