# JSON Codec Wire Contract

How request payloads become bytes for queue push and storage write, and how
those bytes decode back. Implemented in
`scrapy_extension.backends._json_codec` (extracted from `backends.base`, which
re-exports the public names also available at the package root). `Serializer`
and `JSONSerializer` are **Stable**.

`BackendQueue` and `BackendPipeline` serialize with a `JSONSerializer` by
default; their `serializer` attribute is always a `JSONSerializer` instance.

## `Serializer` protocol

A structural protocol for static typing (not `@runtime_checkable` — do not
`isinstance` against it):

```python
class Serializer(Protocol):
    def serialize(self, obj: object) -> bytes: ...
    def deserialize(self, data: bytes) -> object: ...
```

## `JSONSerializer`

- `serialize(obj) -> bytes`: UTF-8 JSON. A recursive encoder walks the value
  tree first (escaping marker-shaped dicts, tagging bytes/datetime/date), then
  `json.dumps(..., allow_nan=False)` handles the rest.
- `deserialize(data) -> object`: marker decode runs inside
  `object_pairs_hook` — the value tree is decoded in a single pass while
  `json.loads` builds it.

### Type handling

| Value type | Wire form | `deserialize` yields |
| ---------- | --------- | -------------------- |
| `None` / `str` / `int` / `float` / `bool` | native JSON | same type |
| `bytes`, `bytearray` | tagged base64 marker | `bytes` |
| `datetime` | tagged ISO 8601 marker | `datetime` |
| `date` | tagged ISO 8601 marker | `date` |
| `Decimal` (finite) | string | `str` — no automatic re-typing |
| `uuid.UUID` | canonical hex string | `str` |
| `set` / `frozenset` | list | `list` (order undefined) |
| `Enum` | its `.value` | the value's type |
| `pathlib.Path` | string | `str` |
| non-finite `float` or `Decimal` | — | `ValueError` |
| `SecretStr` / `SecretBytes` (as value or dict key) | — | terminal `TypeError` |
| anything else | — | `TypeError` naming the type — no silent `str()` coercion |

Verified against the implementation:

```python
>>> from datetime import datetime
>>> from scrapy_extension.backends.base import JSONSerializer
>>> s = JSONSerializer()
>>> s.serialize({"blob": b"hi", "when": datetime(2026, 1, 2, 3, 4, 5)})
b'{"blob": {"__scrapy_extension_json_type__": "bytes", "data": "aGk="}, '
b'"when": {"__scrapy_extension_json_type__": "datetime", "data": "2026-01-02T03:04:05"}}'
>>> s.deserialize(s.serialize({"blob": b"hi", "when": datetime(2026, 1, 2, 3, 4, 5)}))
{'blob': b'hi', 'when': datetime.datetime(2026, 1, 2, 3, 4, 5)}
```

## Marker escaping

The wire tag is `__scrapy_extension_json_type__` with a `data` payload; kinds
are `bytes`, `dict`, `datetime`, and `date`.

- Caller-owned dictionaries that happen to be shaped like a wire marker are
  **escaped** — wrapped in a `dict`-kind marker holding an items list — and
  restored exactly on decode. Marker-shaped user data is never re-typed.
- The legacy `{"__b64__": "<base64>"}` bytes marker is still *read* for
  rolling upgrades from payloads written before the escaped codec, but is
  never written. A dictionary legitimately shaped like it — or carrying
  invalid base64 — decodes unchanged as a plain dictionary.

## Decode guarantees

- Duplicate JSON member names raise `ValueError`; duplicates inside an escaped
  dictionary likewise.
- `NaN` / `Infinity` literals raise `ValueError` (mirroring the
  `allow_nan=False` encode guard).
- Corrupt markers (bad base64, bad ISO string) fall through to the plain
  dictionary — corrupt-but-recoverable values never drop a whole pop.

## Secrets never reach the wire

`SecretStr` / `SecretBytes` — as values or dictionary keys — raise a terminal
`TypeError` with fixed text:

```text
SecretStr values cannot be JSON serialized; explicitly encrypt or
unwrap only after accepting persistence risk.
```

Persist secrets only through explicit caller unwrapping. `secret_value(s)` is
the package helper: a `SecretStr` yields its raw string, a plain `str` (or
`None`) passes through unchanged. It is a convenience accessor, not an
assignment-validation or redaction boundary.

Queue-path serialization failures surface as `SerializationError` whose
`data` attribute is `None` with fixed message text — a deliberate security
boundary pinned in [STABILITY.md](../../.github/STABILITY.md).
