# Audit: Error Handling & Resource Lifecycle

Scope: `backends/_retry.py`, `circuit_breaker.py`, `connectors/_manager.py` (connect/close/lease),
`backends/_generation.py`, all 10 backend `connect()`/`disconnect()` paths, scheduler/pipeline/
dupefilter/spider-mixin close paths, queue lease/ack finalization, cleanup on spider close.
Method: full read of retry/breaker/manager/generation code, disconnect paths of all 10 backends,
scheduler `_close_*` chain, pipeline close, spider mixin close; targeted test runs
(`test_circuit_breaker.py`, `test_connection_manager*.py`, `test_connection_manager_leases.py` — all green, 230+ tests).

## Overall verdict

Error-handling discipline is **exceptionally strong** — far above typical OSS quality:

- No classic swallowed exceptions in data paths. All ~165 `except BaseException: pass` sites are
  deliberate diagnostic-handler guards (`_log_diagnostic` pattern) protecting teardown from hostile
  logging handlers; control-flow exceptions (`KeyboardInterrupt`/`SystemExit`/`GeneratorExit`) are
  consistently exempted from counting, cleanup, and redaction.
- Retry: full-jitter backoff (`_retry.py`) with the R21-C overflow cap; per-manager wait budget
  (`_reactor_io_timeout`); `ConfigurationError`/`ImportError` correctly exempted from network retry.
- Circuit breaker: sound CLOSED→OPEN→HALF_OPEN machine with epoch fencing of late results,
  single-probe slot, `new_generation()` on reconnect (`_manager.py:1700`), correct
  `_DurablePushRequired`/non-failure passthroughs.
- Connection lifecycle: generation-lease gates (`_generation.py`) drain admitted SDK operations
  before handle close; retirement finalization is repairable and idempotent; failed lease releases
  are retained (`_pending_release_*`) and retried on next acquire (`retry_pending_releases`).
- Bounded reactor adapters (`utils/reactor.py`) never cancel authoritative workers; timeouts produce
  typed `BackendOperationTimeout` while ordering chains stay authoritative.

The opportunities below are therefore about **consistency, observability, and closing bounded gaps**,
not fixing structural rot.

## Findings (prioritized)

### P1-1 · Connect-failure message misreports attempt count in the *common* case
`connectors/_manager.py:1862-1869` — after a deadline or retirement `break`, the loop raises
`"Failed to connect after {total_attempts} attempts"` where `total_attempts = retry_attempts + 1`
is the **configured max**, not attempts actually made. With defaults (`retry_attempts=3`,
`retry_delay=1.0` → cumulative backoff ≈7s) and `SCRAPY_REACTOR_IO_TIMEOUT=5s`, deadline truncation
is routine, so the miscount is the typical message, and `on_retry` monitor events disagree with it.
`docs/insight/R133-...-SPEC.md` flagged both halves; only the release-error-preservation half landed.
**Fix:** track `attempts_made`; message + stat `backend/connect_attempts_exhausted`.

### P1-2 · Deferred generation-finalizer errors are recorded but never surfaced
`backends/_generation.py:42,98` — `_run_finalizer` appends cleanup errors to
`GenerationRecord.finalization_errors`; nothing in the package ever reads that list (verified by
grep; only a test asserts recording, `test_mq_generation_leases.py:60`). Kafka/RabbitMQ/RocketMQ/
Pulsar reentrant disconnects defer client close to the last lease release — those close failures
vanish silently. **Fix:** one diagnostic + `backend/disconnect_failure` stat in `_run_finalizer`.

### P1-3 · Breaker state changes and most error seams are invisible to telemetry
`Monitor` has `on_connect/on_disconnect/on_error` but **no breaker hook**; OPEN/HALF_OPEN
transitions emit no stat/log — operators see only per-call static errors. `on_error` is wired at
exactly two seams (queue pop `queue.py:965`, pipeline store `pipeline.py:1378`); push, ack/nack,
dupefilter ops, and connects emit nothing. Scheduler `next_request` folds `QueueError`,
`BackendConnectionError`, and `CircuitBreakerOpenError` into one static log line
(`scheduler.py:3569-3576`) — breaker-open is indistinguishable from transient failure.
**Fix:** `on_breaker_state(name, state)` hook + wire `on_error` at the remaining seams.

### P2-4 · Disconnect cleanup-error taxonomy differs across all 10 backends
Same event — driver `close()`/`shutdown()` raising an ordinary `Exception` — has four outcomes:

| backend | ordinary close failure |
|---|---|
| kafka (sync), rabbitmq, elasticsearch | re-raised |
| rocketmq | swallowed + log, then typed `BackendConnectionError` |
| mongodb, dynamodb | swallowed + diagnostic log |
| sqs, memcached (`_swallow`) | swallowed + debug log |
| redis (`contextlib.suppress(Exception)`, `_close_handles`) | silently suppressed |

Consequence: `on_disconnect_result(succeeded=...)` and the manager's "Error during disconnect"
warning mean different things per backend. **Fix:** one shared
`close_handles(*clients) -> (failed, control_error)` policy helper (fits the documented
ConnectionManager decomposition roadmap); redis is the outlier to align first.

### P2-5 · HALF_OPEN probe has no deadline (last wedge state)
`circuit_breaker.py:_allow_call` — `reset_timeout` gates entry to HALF_OPEN, but once the single
probe is admitted, a hung driver call keeps `_probe_in_flight=True` forever: breaker can never
recover, all traffic fail-fasts with no distinguishing signal. Signals/non-failures correctly
release the slot; only the "probe hangs" case lacks a bound. **Fix:** probe deadline that
re-opens with `last_failure_time=now`, or at minimum surface transitions (see P1-3).

### P2-6 · `retry_attempts`/`retry_delay` silently subordinate to the reactor-wait budget
`_manager.py:1778,1842-1845` — `retry_attempts=20, retry_delay=30` performs **one** attempt
(the deadline expires before the first backoff). Runbook documents each knob mechanically but not
the product interaction; also each attempt's own duration is unbounded (relies on driver socket
timeouts). **Fix:** warn once at manager init when `Σ backoff > retry budget`; document the
worst-case latency formula.

### P3-7 · Static-only error messages sacrifice root-cause discriminability
All boundaries re-raise after the except suite (`raise sanitized_error`, no `from`), so package
errors carry no `__cause__`/`__context__` — deliberate redaction posture, but
`QueueError("Redis queue pop failed.", operation="pop")` covers auth/readonly/cluster-down/timeout
alike. **Fix (high leverage, low risk):** bounded per-driver *category codes* (`auth`, `readonly`,
`timeout`, …) attached to package errors inside each backend — text stays static, taxonomy becomes
actionable; pair with P1-3 counters (`errors/pop:auth`).

### P3-8 · `_on_spider_closed` swallows `close_backend()` failure advisory-only
`spider_mixin.py:834-874` — static error log, no stat, no retry attempt. Mitigated by
`_pending_release_*` + retry-on-next-acquire, but a CrawlerRunner daemon that never re-acquires the
same key waits for process exit. **Fix:** emit a stat and call `retry_pending_releases()` once.

### P3-9 · `_pending_release_leases`/`_pending_release_managers` are unbounded
Shrink only on successful retry; failure storms grow them without bound (contrast with the
`MAX_MANAGERS` LRU discipline). Add a cap + one-shot warning.

### P3-10 · SQS `clear_queue` sleeps the full 60s purge window under the per-queue lock
`sqs.py:1609` — deliberate and documented, admin-path only; but nothing prevents a strategy
`clear()` from reaching it on the reactor thread. Verify/force worker-thread execution.

## Strengths to preserve (regression guard for the plan)
- Ceiling discipline trio: `_MAX_BACKOFF_S`, `THROTTLE_MAX_MIN_INTERVAL_S`,
  `CIRCUIT_BREAKER_MAX_RESET_TIMEOUT_S` (all reject/clamp pathological configs).
- Epoch-fenced breaker admissions (`_CallAdmission`) fencing late old-socket results.
- `BaseException` hygiene: signals never counted as breaker failures, never trapped by `_swallow`,
  never redacted/rewrapped, traceback stripped only after peers cleaned up.
- Generation lease gates: retire → drain → close, with reentrant-disconnect deferral.
- Batched storage close: retry-tail requeue, bounded flush wait, durability barrier before manager
  release; failure keeps manager owned (retryable) — rollback path force-releases.
- `ConnectionManagerLease.release` failure retention makes rollbacks unreachable-leak-proof.
