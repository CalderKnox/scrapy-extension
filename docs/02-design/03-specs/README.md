# Specifications

Behavioral specifications: what the system must do, stated precisely enough
to test against.

## Contents

| Document | Description |
| -------- | ----------- |
| [Generation-fenced delivery](../01-decisions/0001-generation-fenced-delivery.md) | Durable push and acknowledgement invariants |
| [Backend interfaces](../../03-api/backend-interfaces.md) | Normative queue, set, and storage behavior |

The specifications above are the currently maintained behavioral contracts.
Add a standalone spec here when it introduces testable behavior that does not
belong in an API contract or decision record.

Interface and schema contracts belong in [03-api/](../../03-api/); this
directory covers behavior. Ideas still under discussion belong in
[00-rfcs/](../../00-rfcs/).
