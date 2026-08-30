# Documentation

Start here. This directory holds everything beyond the README: proposals,
decisions, design, reference, and operational material.

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

Each directory has a `README.md` describing what belongs there — list new
documents in it. `00-rfcs/`, `01-adrs/`, and `02-design/` also ship a
`_template.md` scaffold to copy when creating a document.

Maintainer execution history — round-based SPEC/PLAN/TASK records and the
insight ledger — lives in [08-archive/insight/](08-archive/insight/).

## Conventions

- One topic per file, named in `kebab-case.md`; RFCs and ADRs use
  `NNNN-<slug>.md` numbering.
- Every subdirectory is indexed by its `README.md`, which GitHub renders
  automatically when browsing; `_template.md` files are scaffolds, not
  documents.
- Prefer linking from prose over duplicating content.

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
