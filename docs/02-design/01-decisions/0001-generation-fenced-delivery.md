# Generation-fenced delivery and durable push

- **Status:** accepted
- **Date:** 2026-07-21
- **Owner:** maintainers
- **Related:** [current architecture](../00-architecture/current-architecture.md), `queue/strategies/base.py`, `backends/base.py`

## Context

Requests can outlive a backend connection. A reconnect may create a new backend
object while an earlier broker delivery remains in flight. Publishing a dedup
marker before an item crosses a worker-crash durability boundary can also strand
a marker with no recoverable request.

## Options

1. Resolve the manager again at callback time and pass the raw token.
2. Treat every successful `push()` as durable.
3. Bind settlement to the issuing backend incarnation and make durability an
   explicit operation receipt.

## Decision

Use option 3. `_BoundQueueAckToken` captures the backend object and physical
queue and settles once. Prepared queue routes return durability evidence;
dependent dedup markers and source acknowledgements require literal `True`.
Unknown or legacy routes fail closed when durability is required.

## Impact

This preserves at-least-once delivery across manager replacement and prevents
false durable claims. Tests must cover concurrent settlement, retry after a
broker failure, and rejection before a non-durable route mutates state.

## Review trigger

Revisit for a new acknowledgement model, manager lease/eviction changes, or a
strategy that stores requests outside its backend.
