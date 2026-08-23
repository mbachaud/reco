"""Canonical JSON serialization and hashing.

Byte-level contract for every state hash, record digest, and commit-chain
link: UTF-8, sorted keys, compact separators, non-ASCII unescaped. Allowed
value types: dict (string keys), list, str, int, bool, None. Floats are
rejected — the simulation is integer-only so a float anywhere is a bug.
"""
import hashlib
import json


class CanonicalizationError(TypeError):
    """Value cannot be represented in canonical form."""


def _validate(value, path="$"):
    if value is None or isinstance(value, (bool, str)):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        raise CanonicalizationError(f"float not allowed at {path}: {value!r}")
    if isinstance(value, list):
        for i, item in enumerate(value):
            _validate(item, f"{path}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError(
                    f"non-string dict key at {path}: {key!r}"
                )
            _validate(item, f"{path}.{key}")
        return
    raise CanonicalizationError(f"unsupported type at {path}: {type(value).__name__}")


def canonical_json(value) -> bytes:
    """Serialize to the canonical byte form."""
    _validate(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_hex(value) -> str:
    """SHA-256 hex digest of the canonical byte form."""
    return hashlib.sha256(canonical_json(value)).hexdigest()
