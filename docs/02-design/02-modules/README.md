# Modules

Per-module design documentation: what each module does, its interfaces, and
its dependencies.

## Contents

| Document | Description |
| -------- | ----------- |
| [Architecture overview](../00-architecture/current-architecture.md) | Component boundaries, lifecycle, and recovery model |
| [Backend interfaces](../../03-api/backend-interfaces.md) | Shared queue, set, and storage contracts implemented by modules |

Module-level notes are being consolidated into the active architecture and API
documents above; add a dedicated module page when a component needs deeper
implementation detail than those contracts provide.

One document per module, named after the module (e.g. `auth.md`). Keep module
docs aligned with the code they describe.
