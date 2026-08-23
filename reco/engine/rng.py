"""Keyed-hash randomness.

Every draw is a pure function of (seed, *key_parts) — hashed through the
canonical JSON form so part boundaries can never collide. There is no shared
consumed stream anywhere in the engine: adding or removing draws in one rule
can never reorder another rule's randomness, which keeps replay stable across
code changes that don't touch a given stream.
"""
import hashlib

from reco.engine.hashing import canonical_json


def derive(seed, *key_parts) -> int:
    """256-bit integer derived from (seed, *key_parts)."""
    payload = canonical_json([seed, *key_parts])
    return int.from_bytes(hashlib.sha256(payload).digest())


def rand_below(seed, n: int, *key_parts) -> int:
    """Uniform integer in [0, n). Modulo bias is ~2**-248 — negligible."""
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    return derive(seed, *key_parts) % n


def permutation(seed, n: int, *key_parts) -> list[int]:
    """Deterministic Fisher-Yates permutation of range(n)."""
    items = list(range(n))
    for i in range(n - 1, 0, -1):
        j = rand_below(seed, i + 1, *key_parts, "fy", i)
        items[i], items[j] = items[j], items[i]
    return items
