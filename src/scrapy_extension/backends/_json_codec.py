"""The escaped recursive JSON codec for queue/storage payloads.

P3-2 (R144): this codec is a cohesive seam of ``backends/base.py`` — the
bytes/datetime/date markers, the escaped-dict collision guards, the
SecretStr terminal rejection, ``Serializer``, ``secret_value``, and
``JSONSerializer`` move together so the backend-interface module carries
only interfaces. ``backends.base`` re-exports the public names.

Wire contract summary (unchanged by the move):

- ``datetime`` / ``date`` / ``bytes`` round-trip through escaped tagged
  markers; caller-owned dicts shaped like a marker are escaped, never
  retyped (the legacy ``__b64__`` marker is still READ for rolling
  upgrades but no longer written).
- SecretStr / SecretBytes are terminal ``TypeError``\ s — secrets reach
  persistent stores only through explicit caller unwrapping.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import NoReturn, Protocol, cast

from pydantic import SecretStr

#: Legacy bytes marker retained for reading payloads written before the escaped
#: codec. New writes use ``_CODEC_TAG`` and escape marker-shaped user dicts.
_BYTES_TAG = "__b64__"

# New bytes markers are escaped before JSON encoding so caller-owned dictionaries
# can use any key/value shape without being retyped during deserialize.
_CODEC_TAG = "__scrapy_extension_json_type__"
_CODEC_DATA = "data"
_CODEC_BYTES = "bytes"
_CODEC_DICT = "dict"
_CODEC_DATETIME = "datetime"
_CODEC_DATE = "date"


class _SecretWrapperSerializationRejected(Exception):
    """Internal signal whose fields contain only a non-sensitive wrapper name."""

    def __init__(self, wrapper_name: str) -> None:
        super().__init__(wrapper_name)
        self.wrapper_name = wrapper_name


def _raise_terminal_secret_serialization_error(wrapper_name: str) -> NoReturn:
    """Raise the public error after all secret-bearing codec frames have unwound."""
    raise TypeError(
        f"{wrapper_name} values cannot be JSON serialized; explicitly encrypt or "
        "unwrap only after accepting persistence risk."
    ) from None


def _json_default(obj: object) -> object:
    """JSON default handler for types Scrapy request dicts commonly contain.

    Handles the types that appear in real-world ``request.meta``:
    - ``datetime`` / ``date`` → tagged ISO 8601 marker (round-trips to the same
      type via ``fromisoformat``; the marker is escaped like the bytes marker so
      caller-owned dicts of the same shape survive untouched)
    - ``bytes`` / ``bytearray`` → tagged base64 marker (the recursive codec
      handles these before this fallback in normal ``JSONSerializer`` use)
    - ``Decimal`` → ``str`` for finite values (preserves exact decimal representation,
      avoids float drift); non-finite (``NaN``/``Infinity``) raises ``ValueError``,
      mirroring the float ``allow_nan=False`` guard
    - ``UUID`` → ``str`` (canonical hex form)
    - ``set`` / ``frozenset`` → ``list`` (JSON has no set type; order undefined)
    - ``Enum`` → ``.value`` (preserves the enum's declared value, not the member)
    - ``pathlib.Path`` → ``str`` (preserves the path representation)

    Everything else raises ``TypeError`` — surfacing the caller's bug rather
    than silently ``str()``-ing it (which produced ``"b'x'"`` for bytes and
    lost the original value).

    Args:
        obj: The non-JSON-native object to convert.

    Returns:
        A JSON-native representation (str, list, int, etc.).

    Raises:
        TypeError: If the object's type isn't handled.
    """
    if isinstance(obj, datetime):
        return {
            _CODEC_TAG: _CODEC_DATETIME,
            _CODEC_DATA: obj.isoformat(),
        }
    if isinstance(obj, date):
        return {
            _CODEC_TAG: _CODEC_DATE,
            _CODEC_DATA: obj.isoformat(),
        }
    if isinstance(obj, (bytes, bytearray)):
        return {
            _CODEC_TAG: _CODEC_BYTES,
            _CODEC_DATA: base64.b64encode(bytes(obj)).decode("ascii"),
        }
    if isinstance(obj, Decimal):
        if not obj.is_finite():
            raise ValueError(f"Cannot serialize non-finite Decimal: {obj!r}")
        return str(obj)
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Path):
        return str(obj)
    type_name = type(obj).__name__
    if type_name in {"SecretStr", "SecretBytes"}:
        raise TypeError(
            f"{type_name} values cannot be JSON serialized; explicitly encrypt or "
            "unwrap only after accepting persistence risk."
        )
    raise TypeError(
        f"Object of type {type_name} is not JSON serializable. "
        f"Pre-serialize {type_name} instances before pushing to the queue, "
        f"or extend scrapy_extension.backends.base._json_default."
    )


def _decode_bytes_tag(obj: object) -> object:
    """Decode the legacy ``{"__b64__": ...}`` bytes marker when valid.

    New writes use the escaped recursive codec. It wraps a caller-owned dict with
    this exact shape, so new serialize → deserialize round trips cannot collide;
    the legacy decoder remains solely for rolling-upgrade compatibility.

    Args:
        obj: A decoded JSON value.

    Returns:
        ``bytes`` for a tagged marker dict; the original dict otherwise.
    """
    if isinstance(obj, dict) and len(obj) == 1:
        value = obj.get(_BYTES_TAG)
        if isinstance(value, str):
            try:
                return base64.b64decode(value, validate=True)
            except (binascii.Error, ValueError):
                # A legitimately-stored dict shaped like {"__b64__": "<non-base64>"}
                # (a spider's own meta key, or a truncated/corrupt value) must NOT
                # crash the entire request deserialize (#31). Fall through: the dict
                # is returned unchanged so the value surfaces as a plain str instead
                # of dropping the whole pop.
                pass
    return obj


def _looks_like_codec_marker(obj: dict[object, object]) -> bool:
    """Whether a caller-owned dict would collide with a supported wire marker."""
    if len(obj) == 1 and isinstance(obj.get(_BYTES_TAG), str):
        return True
    return (
        len(obj) == 2
        and obj.get(_CODEC_TAG)
        # R57: tuple (not set) membership so an UNHASHABLE tag value (list/dict)
        # returns False instead of raising TypeError -- mirrors the decode-side
        # ``== _CODEC_*`` checks and restores encode/decode symmetry for the
        # escape contract.
        in (_CODEC_BYTES, _CODEC_DICT, _CODEC_DATETIME, _CODEC_DATE)
        and _CODEC_DATA in obj
    )


def _encode_json_value(obj: object) -> object:
    """Recursively encode rich types (bytes/datetime/date), escaping marker-shaped dicts."""
    type_name = type(obj).__name__
    if type_name in {"SecretStr", "SecretBytes"}:
        raise _SecretWrapperSerializationRejected(type_name)
    if isinstance(obj, (bytes, bytearray)):
        return {
            _CODEC_TAG: _CODEC_BYTES,
            _CODEC_DATA: base64.b64encode(bytes(obj)).decode("ascii"),
        }
    if isinstance(obj, datetime):
        return {
            _CODEC_TAG: _CODEC_DATETIME,
            _CODEC_DATA: obj.isoformat(),
        }
    if isinstance(obj, date):
        return {
            _CODEC_TAG: _CODEC_DATE,
            _CODEC_DATA: obj.isoformat(),
        }
    if isinstance(obj, dict):
        for key in obj:
            key_type_name = type(key).__name__
            if key_type_name in {"SecretStr", "SecretBytes"}:
                raise _SecretWrapperSerializationRejected(key_type_name)
            if not isinstance(key, str):
                raise TypeError(
                    f"JSON object keys must be strings, got {key_type_name}"
                )
        encoded = {key: _encode_json_value(value) for key, value in obj.items()}
        if _looks_like_codec_marker(encoded):
            return {
                _CODEC_TAG: _CODEC_DICT,
                _CODEC_DATA: list(encoded.items()),
            }
        return encoded
    if isinstance(obj, (list, tuple)):
        return [_encode_json_value(value) for value in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        raise ValueError(f"JSON numbers must be finite, got {obj!r}")
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    return _encode_json_value(_json_default(obj))


def _decode_marker_dict(obj: dict[str, object]) -> object:
    """Decode one marker-shaped dict; return it unchanged when it is not one.

    Children are already decoded when this runs — ``json.loads`` parses
    depth-first, so by the time an object's pairs reach the hook (or, in the
    legacy two-pass form, by the time a parent dict is revisited) every
    nested value has been through this logic already. Marker decode failures
    (bad base64, bad ISO strings) deliberately fall through to the plain
    dict, matching the historical contract for corrupt-but-recoverable
    values.
    """
    data_value: object = obj.get(_CODEC_DATA)
    if (
        len(obj) == 2
        and obj.get(_CODEC_TAG) == _CODEC_DICT
        and isinstance(data_value, list)
    ):
        items: list[object] = data_value
        if all(
            isinstance(pair, list) and len(pair) == 2 and isinstance(pair[0], str)
            for pair in items
        ):
            decoded: dict[str, object] = {}
            for item in items:
                pair = cast("list[str]", item)
                if pair[0] in decoded:
                    raise ValueError(f"Duplicate escaped JSON object key: {pair[0]!r}")
                decoded[pair[0]] = pair[1]
            return decoded

    if len(obj) == 2 and isinstance(data_value, str):
        tag = obj.get(_CODEC_TAG)
        if tag == _CODEC_BYTES:
            try:
                return base64.b64decode(data_value, validate=True)
            except (binascii.Error, ValueError):
                pass
        elif tag == _CODEC_DATETIME:
            try:
                return datetime.fromisoformat(data_value)
            except ValueError:
                pass
        elif tag == _CODEC_DATE:
            try:
                return date.fromisoformat(data_value)
            except ValueError:
                pass

    return _decode_bytes_tag(obj)


def _reject_non_finite_json_constant(value: str) -> object:
    """Reject Python's non-standard NaN/Infinity JSON extensions."""
    raise ValueError(f"JSON numbers must be finite, got {value}")


def _parse_finite_json_float(value: str) -> float:
    """Parse a JSON float and reject exponent overflow to infinity.

    ``json.loads`` only invokes ``parse_constant`` for the non-standard literal
    spellings ``NaN`` and ``Infinity``.  A standards-compliant number such as
    ``1e309`` can still overflow Python's ``float`` conversion to ``inf``;
    validate the converted value here so all decoded numbers remain finite.
    """
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"JSON numbers must be finite, got {value}")
    return parsed


def _json_object_from_pairs(pairs: list[tuple[str, object]]) -> object:
    """Build one JSON object, decode markers, and reject duplicate names.

    Single pass (P1-5): the historical form built plain dicts here and
    re-walked the finished tree in ``_decode_json_value``. Because
    ``json.loads`` parses depth-first, every nested value is already decoded
    by the time its containing object's pairs arrive — so the marker decode
    folds into this hook and the second tree walk disappears. Duplicate
    member names are rejected while building, preserving the ambiguity
    contract; escaped-dict duplicates are rejected in ``_decode_marker_dict``.
    """
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key!r}")
        result[key] = value
    return _decode_marker_dict(result)


def secret_value(s: SecretStr | str | None) -> str | None:
    """Extract the raw string from a SecretStr (or pass through plain str).

    Bundled settings wrap post-construction string assignments immediately.
    Plain strings remain supported here for direct backend/plugin compatibility;
    this helper is not an assignment-validation or redaction boundary.

    Args:
        s: A SecretStr, compatibility plain string, or None.

    Returns:
        The secret's raw string value, or None.
    """
    if s is None:
        return None
    if isinstance(s, SecretStr):
        return s.get_secret_value()
    return s


class Serializer(Protocol):
    """Protocol for serializers.

    Any class implementing this protocol can be used for serializing
    and deserializing data for backend storage.
    """

    def serialize(self, obj: object) -> bytes:
        """Serialize an object to bytes.

        Args:
            obj: The object to serialize.

        Returns:
            The serialized bytes.
        """
        ...

    def deserialize(self, data: bytes) -> object:
        """Deserialize bytes to an object.

        Args:
            data: The bytes to deserialize.

        Returns:
            The deserialized object.
        """
        ...


class JSONSerializer:
    """JSON serializer implementation.

    Uses Python's json module for serialization. Suitable for
    serializing basic Python types and simple objects.
    """

    def serialize(self, obj: object) -> bytes:
        """Serialize an object to JSON bytes.

        Uses an escaped recursive codec plus ``_json_default`` for common
        non-JSON-native types found in Scrapy request dicts (``datetime`` / ``date``
        and ``bytes`` → tagged ISO / base64 markers that round-trip).
        Truly unexpected types raise TypeError with a clear message — no silent
        ``str()`` coercion.

        Args:
            obj: The object to serialize.

        Returns:
            JSON-encoded bytes.

        Raises:
            TypeError: If the object contains types not handled by _json_default.
        """
        try:
            return json.dumps(
                _encode_json_value(obj),
                default=_json_default,
                allow_nan=False,
            ).encode("utf-8")
        except _SecretWrapperSerializationRejected as source_error:
            wrapper_name = source_error.wrapper_name

        # Reconstruct at a terminal boundary only after the internal exception and
        # its secret-bearing codec frames have unwound. Removing the public frame's
        # receiver and input prevents the replacement traceback from retaining the
        # serializer, caller container, wrapper, or underlying secret.
        del self, obj
        _raise_terminal_secret_serialization_error(wrapper_name)

    def deserialize(self, data: bytes) -> object:
        """Deserialize JSON bytes to an object.

        Reverses escaped current bytes markers and legacy ``{"__b64__": ...}``
        markers. Marker-shaped caller dictionaries remain dictionaries. The
        marker decode runs inside ``object_pairs_hook`` (single pass — the
        value tree is decoded as ``json.loads`` builds it).

        Args:
            data: The JSON bytes to deserialize.

        Returns:
            The deserialized object.
        """
        return json.loads(
            data.decode("utf-8"),
            parse_constant=_reject_non_finite_json_constant,
            parse_float=_parse_finite_json_float,
            object_pairs_hook=_json_object_from_pairs,
        )


# Shared utilities for backends

# Uses \Z instead of $ so the pattern only matches at the string's absolute
