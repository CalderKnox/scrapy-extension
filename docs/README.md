# Documentation

Start here. This directory holds everything beyond the [project README](../README.md):
proposals, decisions, design, reference, and operational material. Use the
shortest path below for the job at hand; each section README then links to the
documents in that section.

## Common paths

| If you are... | Start with |
| --- | --- |
| New to the project | [Guides](06-guides/) and the [runnable examples](../examples/README.md) |
| Integrating a backend | [Backend interfaces](03-api/backend-interfaces.md) and [backend configuration](../README.md#backend-configuration) |
| Operating a deployment | [Runbook](05-runbooks/runbook.md) |
| Upgrading an existing deployment | [Migration guide](06-guides/user-guides/migration-guide.md) |
| Writing a backend plugin | [Plugin guide](06-guides/developer-guides/backend-plugins.md) |
| Proposing an architectural change | [RFCs](00-rfcs/) and [ADRs](01-adrs/) |

## Contents

Directories are numbered in lifecycle order — from proposing a change to
operating the built system:

| Directory                      | Purpose                                            |
| ------------------------------ | -------------------------------------------------- |
| [00-rfcs/](00-rfcs/)           | Proposals for significant changes, open for review |
| [01-adrs/](01-adrs/)           | Architecture decision records (ADRs)               |
| [02-design/](02-design/)       | System design: components, diagrams, data flows    |
| [03-api/](03-api/)             | API contracts and schema reference                 |
| [04-playbooks/](04-playbooks/) | How-to guides for recurring tasks                  |
| [05-runbooks/](05-runbooks/)   | Operational procedures: deploy, monitor, respond   |
| [06-guides/](06-guides/)       | Developer, user, and tutorial guides               |
| [07-reference/](07-reference/) | Reference material: glossary, configuration        |
| [08-archive/](08-archive/)     | Superseded and historical documents                |

Each visible documentation directory has a `README.md` describing what
belongs there and a local `_template.md` scaffold to copy when creating a
document. Templates are
directory-specific, but use the same metadata order, heading style, and
placeholder conventions.

To add a document: choose the section using the table below, copy that
section's `_template.md`, replace every placeholder, then add the new file to
the section README. Keep links relative so the docs remain usable in a source
checkout and on GitHub. Run the documentation checks locally before opening a
pull request (the same checks run in `.github/workflows/docs.yml`).

The live risk register is
[insight-2026-09-24](02-design/00-architecture/insight-2026-09-24.md).
Maintainer execution history — round-based SPEC/PLAN/TASK records and the
insight ledger — lives in [08-archive/insight/](08-archive/insight/).

## Conventions

- One topic per file, named in `kebab-case.md`; RFCs and ADRs use
  `NNNN-<slug>.md` numbering.
- Keep the metadata block immediately below the title. Use ISO dates
  (`YYYY-MM-DD`), lowercase lifecycle statuses, and links rather than copied
  text.
- Every directory is indexed by its `README.md`, which GitHub renders
  automatically when browsing; `_template.md` files are scaffolds, not
  documents.
- Prefer linking from prose over duplicating content.

## Document quality

The Documentation quality workflow checks every visible docs directory for an
index and a local template, and verifies key cross-links on pushes and pull
requests.

`01-adrs/` and `02-design/01-decisions/` are complementary:

| Use | `01-adrs/` | `02-design/01-decisions/` |
| --- | --- | --- |
| Scope | Cross-cutting or externally visible architecture | Local implementation or component trade-off |
| Authority | Durable project decision | Working design note |
| Change policy | Append a superseding ADR; preserve history | Update as the design evolves |

If a design note gains cross-cutting impact or creates a long-lived
compatibility promise, promote it to an ADR and link the replacement from the
original note.

## Where does my document go?

| You want to...                                   | Put it in       |
| ------------------------------------------------ | --------------- |
| Propose a significant change before building it  | `00-rfcs/`      |
| Record a decision that was made                  | `01-adrs/`      |
| Describe how the system works                    | `02-design/`    |
| Pin down an interface, schema, or API contract   | `03-api/`       |
| Walk someone through a recurring task            | `04-playbooks/` |
| Document how to operate the system in production | `05-runbooks/`  |
| Onboard a contributor or explain team workflow   | `06-guides/`    |
| Look up terms, configuration, or environment details | `07-reference/` |
| Find superseded or retired documents             | `08-archive/`   |
