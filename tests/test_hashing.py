"""Canonical hashing spec tests.

The canonical form is the byte-level contract every state hash, digest, and
commit-chain link depends on. These tests pin it permanently:
UTF-8, sorted keys, compact separators, non-ASCII unescaped,
integers/bools/None/str/list/dict only — floats and non-string keys rejected.
"""
import pytest

from reco.engine.hashing import CanonicalizationError, canonical_json, sha256_hex


class TestCanonicalJson:
    def test_key_order_does_not_change_bytes(self):
        a = canonical_json({"x": 1, "y": [2, 3], "z": {"a": 1, "b": 2}})
        b = canonical_json({"z": {"b": 2, "a": 1}, "y": [2, 3], "x": 1})
        assert a == b

    def test_pinned_spec_vector(self):
        # Pinned forever: {"b": 1, "a": [True, None, "é"]} canonicalizes to
        # exactly these 28 UTF-8 bytes.
        data = {"b": 1, "a": [True, None, "é"]}
        expected = '{"a":[true,null,"é"],"b":1}'.encode("utf-8")
        assert canonical_json(data) == expected
        assert len(canonical_json(data)) == 28

    def test_rejects_floats_at_top_level(self):
        with pytest.raises(CanonicalizationError):
            canonical_json(1.5)

    def test_rejects_floats_nested(self):
        with pytest.raises(CanonicalizationError):
            canonical_json({"ok": 1, "nested": [{"deep": 2.0}]})

    def test_rejects_non_string_dict_keys(self):
        # json.dumps would silently coerce 1 -> "1", colliding with a real "1" key.
        with pytest.raises(CanonicalizationError):
            canonical_json({1: "x"})

    def test_rejects_unsupported_types(self):
        with pytest.raises(CanonicalizationError):
            canonical_json({"x": {1, 2}})

    def test_bools_are_json_bools_not_ints(self):
        assert canonical_json({"t": True, "f": False}) == b'{"f":false,"t":true}'

    def test_large_ints_survive_exactly(self):
        n = 2**80 + 7
        assert canonical_json(n) == str(n).encode()


class TestSha256Hex:
    def test_pinned_hash_of_spec_vector(self):
        # sha256 of the 28 spec-vector bytes above, computed from the byte
        # spec independently of the implementation.
        data = {"b": 1, "a": [True, None, "é"]}
        assert (
            sha256_hex(data)
            == "17c8c6f7f948ee1c9b93b1bc35f6edc29cbaf3022bff7d076d1c4831dd8a44a2"
        )

    def test_equal_objects_equal_hash(self):
        assert sha256_hex({"a": 1, "b": 2}) == sha256_hex({"b": 2, "a": 1})

    def test_different_objects_different_hash(self):
        assert sha256_hex({"a": 1}) != sha256_hex({"a": 2})
