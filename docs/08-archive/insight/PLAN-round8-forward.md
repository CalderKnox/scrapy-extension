# PLAN — Round 8: Forward Insight (post-hardening, v1.0 readiness)

The **first full forward-looking insight pass** after the rounds 1-7 hardening arc
closed every correctness/security gap (see [`PLAN-round7-recursive-cleanup.md`](./PLAN-round7-recursive-cleanup.md)
RESOLUTION table). This document is NOT a bug list — it is a **v1.0-readiness
roadmap** synthesized for future `/goal` invocations to execute against.

Method: 6-agent parallel fan-out (architect/opus, code-reviewer/opus, critic/opus,
test-engineer/sonnet, scientist/sonnet, explore/haiku). 5 returned structured
findings; **explore (haiku) hit its context-window limit** — structural-inventory
data below is reconstructed from the other 5 agents' file:line citations (a
dedicated structural sweep is a cheap follow-up). Every finding below is
attributed; cross-agent corroboration is marked.

---

## v1.0 verdict (critic, corroborated)

**Not ready.** The hardening arc closed every *code-correctness* gap convincingly
(1353 tests, real-broker integration paths exist, ack/crash-mid-ack/circuit-breaker/
cuckoo-full all genuinely fixed). But v1.0 is a **trust** commitment, not a
correctness one, and the trust layer is one doc-and-observability pass short.
Three non-negotiables before tag (critic V1/V2/M1, 3-way corroborated by
architect + test-engineer):

1. **README honesty** — a per-feature "Distributed? (cross-worker)" Guarantees
   table demoting Bloom/Cuckoo/Delay/Throttle/RoundRobin/Memory from "features"
   to "per-process opt-in." Today the README sells "Distributed crawling" while
   3/4 queue strategies and 3/4 dedup filters are per-process-with-a-warning.
2. **Operability beyond counters** — at minimum `queue/pop_rate_1m` and
   `dupefilter/filter_saturation` gauges so an operator can diagnose a
   0-req/min crawl without filing an issue.
3. **One real multi-backend e2e test** (gated like the existing integration
   suite) pushing a request through 3 live backends — today the "coexistence"
   claim rests on a factory-resolution mock.

---

## Corroboration matrix (load-bearing findings)

| ID | Finding | architect | code-reviewer | critic | test-eng | scientist | Verdict |
|---|---|:-:|:-:|:-:|:-:|:-:|---|
| F01 | Real-broker integration CI (the distributed-claim credibility gate) | ✓ F-12 | — | ✓ M1 | ✓ F2 | — | **CONFIRMED 3-way** |
| F02 | README Guarantees table (honest per-process vs distributed) | ✓ F-6 | — | ✓ A1/V1 | — | — | **CONFIRMED** (v1.0 #1) |
| F03 | Operability signals (pop_rate, filter_saturation, worker liveness) | ✓ F-2 | — | ✓ O1/V2 | — | — | **CONFIRMED** (v1.0 #2) |
| F04 | Dedup default-set strategy = 4 RTT/req → ~1k req/s LAN ceiling | — | — | — | — | ✓ F4-RTT (measured) | **CONFIRMED** (quantified) |
| F05 | Per-pop `queue_len` RTT (+25% pop budget, unconditional) | — | — | — | — | ✓ F2-DEPTH (measured) | **CONFIRMED** (quantified) |
| F06 | Unbounded in-process memory (MemoryMembershipFilter `maxsize=None`) | — | — | — | — | ✓ F5-MEM (measured ~481B/entry) | **CONFIRMED** (quantified) |
| F07 | Mutation testing absent (coverage≠caught-bugs) | — | — | — | ✓ F1 | — | **CONFIRMED** |
| F08 | Property tests spot-wise only (3 `@given`); no strategy/circuit-breaker state-machine | — | — | — | ✓ F3 | — | **CONFIRMED** |
| F09 | Zero perf benchmarks (pytest-benchmark configured, 0 used) | — | — | — | ✓ F4 | — | **CONFIRMED** |
| F10 | Settings reference doc absent (settings only in pydantic docstrings) | — | ✓ DX-03 | — | — | — | **CONFIRMED** |
| F11 | `mypy --strict` not clean (25 errors; `py.typed` promise undercut) | — | ✓ DX-07 | — | — | — | **CONFIRMED** |
| F12 | Error messages lack fix-hints on connection/ES paths (DynamoDB is the A-grade template) | — | ✓ DX-08 | — | — | — | **CONFIRMED** |
| F13 | Distributed strategies as FEATURES (durable Delay, shared Throttle, distributed Bloom) | ✓ F-1 | — | ✓ A2 | — | ✓ F4-BLOOM | **CONFIRMED 3-way** |
| F14 | v1.0 stability artifacts missing (STABILITY.md, SECURITY.md, CHANGELOG, release runbook) | ✓ F-6 | ✓ DX-04/05 | ✓ G2 | — | — | **CONFIRMED 3-way** |

---

## Quantified performance ceilings (scientist — measured, Python 3.14/arm64)

RTT figures are typical-Redis estimates (HYPOTHESIS — confirm with a live broker);
CPU figures are measured microbenchmarks (50k ops, single-core).

| Path | Cost | Scale where it bites |
|---|---|---|
| **Default `set` dedup: 4 RTT/req** (SADD + push-EVAL + pop-EVAL + ZCARD) | ~3,125 req/s loopback · **~1,000 req/s LAN** · ~312 req/s WAN | **Any non-trivial crawl on LAN Redis** — the dominant hot-path cost, 60-200× every CPU component |
| **Per-pop `queue_len` (ZCARD every pop)** via `monitor.on_queue_depth` | +1 RTT/pop = **+25% pop-path budget** | Immediately at any non-trivial rate; 10k pop/s = 10k extra ZCARD/s |
| **`MemoryMembershipFilter` unbounded** (`maxsize=None` default) | ~481 B/entry → **~366 MB @ 1M entries · ~3.58 GB @ 10M** | Long crawls with high URL cardinality → silent OOM |
| Serialization codec (`_request_to_dict` + json) | push 4.30 µs / pop 2.81 µs → ~140k req/s ceiling | **Does NOT bite before RTTs** — defer until RTT wins land |
| Monitor CPU (inc/set per pop) | 0.12 µs/pop = 0.12% CPU @ 10k req/s | Never — below noise floor |
| Circuit-breaker lock | 0.09 µs/acquire (CLOSED fast path) | Only under failure storms |

**Key insight (scientist):** RTTs dominate 60-200× over CPU. The most-tempting
optimization (orjson codec, F1-SER) is the **wrong** first move — it gives <2%
until RTTs are addressed. Fix dedup batching + queue_len sampling first.

---

## Work units (prioritized by leverage × 1/effort, v1.0-oriented)

Each unit is self-contained for a future `/goal` to execute. Tier-1 = v1.0
non-negotiables + cheap high-leverage; Tier-2 = feature/differentiation;
Tier-3 = deferred.

### Tier 1 — v1.0 readiness + quick wins

#### U1 — README Guarantees table `[F02, critic V1, H/S]`

**Why:** "Distributed" marketing is one layer above reality; the first prod
incident is a user re-crawling the entire site because Bloom/Cuckoo are
per-process. **Files:** `README.md` (new "Guarantees" section: per-feature
table with column "Distributed? (cross-worker)" Yes/No/Default-only; demote
Bloom/Cuckoo/Delay/Throttle/RoundRobin/Memory to "per-process opt-in"). **TDD:**
N/A (docs). **Acceptance:** a new user can answer "is feature X cross-worker
safe?" from the README alone. Default `set` called out as distributed-exact.

#### U2 — Operability signals `[F03, critic O1/V2, H/M]`

**Why:** An operator paged on a 0-req/min crawl sees counters stop but cannot
distinguish backend-down / queue-empty / throttle-pinned / dedup-saturated /
worker-crash. **Files:** `monitor/base.py` + `monitor/stats.py` (new hooks
`on_pop_rate` rolling 1m delta, `on_filter_saturation` cuckoo `_count/_capacity`
gauge); `dupefilter/filters/cuckoo_filter.py` (expose saturation); emit from
`queue/queue.py` pop path. **TDD:** rolling-window rate test; saturation gauge
test. **Acceptance:** a stuck crawl produces a diagnostic signal, not just
flat counters.

#### U3 — Multi-backend e2e integration test `[F01, critic M1, H/L]`

**Why:** `test_three_backends_coexist_from_one_settings` only asserts
`from_settings` resolves 3 backend types — **no request flows through
Redis-queue → MongoDB-dedup → ES-storage**. The coexistence claim is unit-mocked.
**Files:** `tests/integration/test_multi_backend_e2e.py` (NEW, gated on
`SCRAPY_TEST_REDIS_URL` + `_MONGO_URI` + `_ES_URL`); optional
`tests/integration/docker-compose.yml`. **TDD:** enqueue N → dedup → store →
assert ordering + set-membership + storage TTL across 3 live backends. **Acceptance:**
one green e2e proves the multi-backend runtime, not just the factory seam.

#### U4 — `queue_len` sampling `[F05, scientist F2-DEPTH, H/S — 1-line]`

**Why:** ZCARD fires on every pop (+25% pop RTT budget); depth changes slowly
vs pop rate. **Files:** `queue/queue.py:197-205` (sample `on_queue_depth` every
Nth pop, e.g. N=100). **TDD:** depth still fresh within sampling window; 100×
fewer `queue_len` calls. **Acceptance:** 9,900 fewer ZCARD/s @ 10k pop/s;
backpressure signal unchanged.

#### U5 — Memory default cap `[F06, scientist F5-MEM, M/S]`

**Why:** `MemoryMembershipFilter(maxsize=None)` silently grows to GB scale →
silent OOM in prod. The LRU `maxsize` mechanism already exists — just ship a
sane default. **Files:** `dupefilter/filters/memory_filter.py:32` (default
`maxsize=1_000_000`); `queue/strategies/delay.py:69` (soft-cap + warn on
`_holding` heap). **TDD:** cap reached → LRU evicts (not grow); warn fires.
**Acceptance:** no unbounded growth by default; operator can tune.

#### U6 — Mutation testing `[F07, test-eng F1, H/S]`

**Why:** Coverage is 95% but coverage ≠ caught-bugs. The hardest historical
bugs (R31 "False=existed", at-least-once ack) are boolean-flip class — exactly
what mocks can't pin. **Files:** add `mutmut` to dev deps; `pyproject.toml`
config (`paths_to_mutate=src/scrapy_extension/backends/redis.py,dupefilter/filters/`);
CI gate. **TDD:** mutmut itself IS the test. **Acceptance:** mutmut run green
or survivor-list converted to targeted tests (F08/F10).

#### U7 — Settings reference doc `[F10, code-reviewer DX-03, H/M]`

**Why:** Every `SCRAPY_*` setting is discoverable only by reading source.
Biggest "can a user configure this without reading source?" gap.
**Files:** `docs/settings-reference.md` (NEW — table per category: Backend /
Dedup / Queue / Pipeline, each `SCRAPY_*` key with type + default + description;
auto-generatable from pydantic field metadata). **Acceptance:** single-page
discovery of all settings.

#### U8 — `mypy --strict` clean `[F11, code-reviewer DX-07, M/S]`

**Why:** `py.typed` is a public promise; 25 `--strict` errors (mostly
`Collection` missing type-args, `Any`-return leaks) undercut it. **Files:**
`pyproject.toml` (`disallow_any_generics=true`, `warn_return_any=true`); fix
the 25 errors (mongodb.py:88,89,458,640; elasticsearch.py:493,521; etc.).
**Acceptance:** `uv run mypy --strict src/scrapy_extension` clean.

#### U9 — v1.0 stability artifacts `[F14, architect F-6 + critic G2, H/S]`

**Why:** v1.0 implies a stability commitment; the artifacts it requires are
absent. **Files:** `STABILITY.md` (component tiers: stable/experimental/internal
— mark RocketMQ experimental per critic B1), `SECURITY.md` (disclosure path;
note `[rocketmq]`/`[all]` supply-chain gate), `CHANGELOG.md`, `docs/release-runbook.md`.
**Acceptance:** a downstream user knows which surface is frozen vs experimental.

### Tier 2 — differentiation / features

#### U10 — Distributed strategies as features `[F13 3-way, architect F-1, H/L]`

**Why:** Converts round-7's accepted scope limitations into advertised
capabilities. **Design:** extend strategy ABC with optional backend-capability
requirements (`requires_zset`, `requires_incr_ttl`); negotiate against
`BackendDescriptor` at selection (no silent degrade). 3 sub-units: durable Delay
(Redis ZSET heap), shared Throttle (INCR+EXPIRE token bucket), distributed
Bloom (backend bit-array). **Acceptance:** a 2-worker crawl shares delayed
items + throttle rate + dedup state. (Largest unit — sequence after Tier 1.)

#### U11 — Batch queue API `[architect F-4, H/M]`

**Why:** Every push/pop is per-item (1 RTT/req). `push_batch`/`pop_batch` on
`QueueBackend` ABC (default loop fallback); wire scheduler batch-drain. Redis
pipeline, Kafka producer batching, Mongo `insert_many` all native. **Acceptance:**
batch=100 → ~100× RTT reduction on enqueue.

#### U12 — OTel monitor `[architect F-2, H/M]`

**Why:** `Monitor` ABC is the right seam; `ScrapyStatsMonitor` is the only
impl. `OTelMonitor` emits spans (`queue.push/pop`, `dedup.hit`, `store`) with
per-backend attributes. **Acceptance:** `SCRAPY_OTEL_EXPORTER_ENDPOINT` wired.

#### U13 — Alt serializers `[architect F-7, scientist F1-SER, M/S — but DEFER]`

**Why:** msgspec/cbor2 3-5× codec speedup. **BUT scientist measured codec is
4.3µs vs RTT 250-1000µs → <2% until RTTs fixed.** Defer until U4/U11 land.

### Tier 3 — deferred / pilot

- **U14 — Async backends** `[architect F-5, M/L]` — highest-uncertainty; pilot
  Redis-only (`redis.asyncio`) before any broad push. Sync-only today is
  documented (`scheduler.py:310`).
- **U15 — Capability-richness descriptor** `[architect F-8]` — replace flat
  `capabilities` frozenset with `BackendCapabilities` dataclass
  (`atomic_pop`/`requires_ack`/`supports_batch`/`ordering`).
- **U16 — RocketMQ resolution** `[architect F-11, critic B1]` — 30-min
  maintained-replacement audit; either dep swap or deprecate-to-stub + mark
  Experimental (overlaps U9).
- **U17 — Property tests + benchmarks** `[test-eng F3/F4/F8/F11]` —
  serialization round-trip, strategy invariants, circuit-breaker state machine;
  pytest-benchmark push/pop p50 gate. Sequence after U6 (mutmut survivors
  dictate where).
- **U18 — Structural inventory sweep** `[explore, context-limited this pass]` —
  module sizes vs 800-LOC ceiling, dead-code/unreachable-branch audit, public
  API surface coherence. Cheap dedicated sweep to fill the gap left by the
  explore agent's context limit.

---

## Recommended next `/goal` (sequencing)

1. **U1 + U4 + U5 + U8** as one cheap-wins round (all H×1/effort, ~1 day) —
   README honesty + 1-line perf + OOM cap + mypy strict. Maximum v1.0-trust
   delta per unit effort.
2. **U2 + U6** as an observability+trust round — operability signals + mutation
   testing gate.
3. **U3 + U9** as the v1.0-credibility round — e2e multi-backend test +
   stability artifacts. **After this, the 3 v1.0 non-negotiables are met.**
4. **U10** (distributed strategies) as the post-1.0 differentiation arc.
5. **U11/U12** (batch API + OTel) as the scale/observability arc.

---

## Non-goals (this is an insight/plan, not execution)

- **Executing any work unit** — that is the job of future `/goal` invocations.
- **Re-opening round-7 ACCEPT'd items** — Delay/Throttle/Bloom per-process scope
  is settled for *correctness*; U10 re-frames them as *features*, not bug fixes.
- **Re-running the explore agent** in-loop — U18 is a cheap dedicated sweep;
  re-running the failed breadth agent mid-loop is brute force.

## Subsequent /loop fires = incremental

Per the `/loop` directive ("首次全量, 后续增量"): future 10-min fires should
**diff against this document** — only surface NEW findings or changes since the
last INSIGHTS, not re-run the full 6-agent pass. Incremental lens: did any
Tier-1 unit land? did a new file exceed 600 LOC? did a new `SCRAPY_*` setting
land without a settings-reference row?
