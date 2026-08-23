"""Tolerant action parsing: the runner extracts candidate actions from raw
model text, rejects malformed actions individually (PE_SCHEMA), and only
total failure idles the tick (PE_MALFORMED). No LLM repair, no silent drops."""
from reco.runner.parse import parse_actions


def ok(raw):
    result = parse_actions(raw)
    assert result["code"] is None, result
    return result


class TestCleanJson:
    def test_plain_array(self):
        r = ok('[{"verb": "move", "path": [[3, 4]]}, {"verb": "harvest"}]')
        assert len(r["actions"]) == 2
        assert r["actions"][0]["verb"] == "move"
        assert r["errors"] == []

    def test_empty_array_is_valid_idle(self):
        r = ok("[]")
        assert r["actions"] == []


class TestTolerance:
    def test_markdown_fenced(self):
        r = ok('Here is my plan:\n```json\n[{"verb": "harvest"}]\n```\nDone!')
        assert r["actions"] == [{"verb": "harvest"}]

    def test_prose_around_array(self):
        r = ok('I will gather wood. [{"verb": "harvest"}] That is my move.')
        assert r["actions"] == [{"verb": "harvest"}]

    def test_trailing_commas(self):
        r = ok('[{"verb": "harvest",},]')
        assert r["actions"] == [{"verb": "harvest"}]

    def test_single_quotes(self):
        r = ok("[{'verb': 'say', 'text': 'hello'}]")
        assert r["actions"] == [{"verb": "say", "text": "hello"}]

    def test_single_object_wrapped_to_list(self):
        r = ok('{"verb": "harvest"}')
        assert r["actions"] == [{"verb": "harvest"}]

    def test_nested_brackets_in_strings_survive(self):
        r = ok('[{"verb": "say", "text": "use path [[1,2]] ok"}]')
        assert r["actions"][0]["text"] == "use path [[1,2]] ok"


class TestPerActionSchema:
    def test_non_dict_entry_rejected_individually(self):
        r = ok('[{"verb": "harvest"}, "just a string", {"verb": "eat", "item": "berries"}]')
        assert len(r["actions"]) == 2
        assert len(r["errors"]) == 1
        assert r["errors"][0]["code"] == "PE_SCHEMA" and r["errors"][0]["index"] == 1

    def test_missing_verb_rejected_individually(self):
        r = ok('[{"path": [[1, 2]]}, {"verb": "harvest"}]')
        assert r["actions"] == [{"verb": "harvest"}]
        assert r["errors"][0]["code"] == "PE_SCHEMA"

    def test_bad_arg_types_rejected(self):
        r = ok('[{"verb": "move", "path": "north"}, {"verb": "say", "text": 42}]')
        assert r["actions"] == []
        assert [e["code"] for e in r["errors"]] == ["PE_SCHEMA", "PE_SCHEMA"]

    def test_unknown_verbs_pass_through_to_engine(self):
        # Engine is the authority on verb validity (R_UNKNOWN_VERB).
        r = ok('[{"verb": "teleport", "anywhere": true}]')
        assert r["actions"] == [{"verb": "teleport", "anywhere": True}]


class TestTotalFailure:
    def test_no_json_at_all(self):
        r = parse_actions("I think I should gather wood this turn.")
        assert r["code"] == "PE_MALFORMED" and r["actions"] == []

    def test_empty_text(self):
        assert parse_actions("")["code"] == "PE_EMPTY"
        assert parse_actions("   \n ")["code"] == "PE_EMPTY"

    def test_hopelessly_broken_json(self):
        r = parse_actions('[{"verb": "mo')
        assert r["code"] == "PE_MALFORMED"
