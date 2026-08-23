"""Tolerant action parsing — the runner's ONLY job on the response path.

Pipeline: strict JSON -> trailing-comma fix -> Python-literal fallback ->
fenced-block extraction -> quote-aware balanced-bracket extraction. A lone
object is wrapped into a one-action list. Entries then get structural
per-action validation: bad shape -> individual PE_SCHEMA error; unknown verbs
pass through untouched (the engine owns verb validity). Only total parse
failure idles the tick. Never any LLM-based repair.
"""
import ast
import json
import re

_FENCE = re.compile(r"```(?:[a-zA-Z]+)?\s*\n(.*?)```", re.DOTALL)
_TRAILING_COMMAS = re.compile(r",\s*([\]}])")

# Structural specs: required arg name -> checker. Unknown verbs are not listed
# and pass through untouched.
_CHECKERS = {
    "str": lambda v: isinstance(v, str),
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "path": lambda v: (
        isinstance(v, list)
        and all(
            isinstance(p, list) and len(p) == 2
            and all(isinstance(c, int) and not isinstance(c, bool) for c in p)
            for p in v
        )
    ),
    "goods": lambda v: (
        isinstance(v, dict)
        and all(
            isinstance(k, str) and isinstance(q, int) and not isinstance(q, bool)
            for k, q in v.items()
        )
    ),
}

_ARG_SPECS = {
    "move": {"path": "path"},
    "say": {"text": "str"},
    "dm": {"to": "str", "text": "str"},
    "remember": {"text": "str"},
    "lookup": {"topic": "str"},
    "eat": {"item": "str"},
    "craft": {"recipe": "str"},
    "build": {"building": "str"},
    "contribute": {"item": "str"},
    "offer": {"to": "str", "give": "goods", "want": "goods"},
    "accept": {"offer_id": "str"},
    "harvest": {},
    "study": {"profession": "str"},
    "claim": {"x": "int", "y": "int"},
    "grant": {"to": "str", "x": "int", "y": "int"},
    "revoke": {"to": "str", "x": "int", "y": "int"},
    "create_currency": {"name": "str"},
    "mint": {"currency": "str", "amount": "int"},
    "set_prices": {"item": "str", "currency": "str", "sell": "int"},
    "stock": {"item": "str", "qty": "int"},
    "withdraw": {"item": "str", "qty": "int"},
    "buy": {"item": "str", "qty": "int"},
}
_OPTIONAL_SPECS = {
    "contribute": {"qty": "int"},
    "offer": {"give_credits": "goods", "want_credits": "goods"},
}


def parse_actions(raw: str) -> dict:
    if raw is None or not raw.strip():
        return {"actions": [], "errors": [], "code": "PE_EMPTY"}

    data = _extract(raw)
    if data is None:
        return {"actions": [], "errors": [], "code": "PE_MALFORMED"}
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return {"actions": [], "errors": [], "code": "PE_MALFORMED"}

    actions, errors = [], []
    for i, entry in enumerate(data):
        problem = _structural_problem(entry)
        if problem:
            errors.append({"index": i, "code": "PE_SCHEMA", "reason": problem})
        else:
            actions.append(entry)
    return {"actions": actions, "errors": errors, "code": None}


def _structural_problem(entry) -> str | None:
    if not isinstance(entry, dict):
        return f"action must be an object, got {type(entry).__name__}"
    verb = entry.get("verb")
    if not isinstance(verb, str):
        return "action has no string 'verb'"
    spec = _ARG_SPECS.get(verb)
    if spec is None:
        return None  # unknown verb: engine's call
    for arg, kind in spec.items():
        if arg not in entry:
            return f"{verb}: missing required arg {arg!r}"
        if not _CHECKERS[kind](entry[arg]):
            return f"{verb}: arg {arg!r} has wrong type"
    for arg, kind in _OPTIONAL_SPECS.get(verb, {}).items():
        if arg in entry and not _CHECKERS[kind](entry[arg]):
            return f"{verb}: arg {arg!r} has wrong type"
    return None


def _extract(raw: str):
    for candidate in _candidates(raw):
        data = _try_parse(candidate)
        if data is not None:
            return data
    return None


def _candidates(raw: str):
    yield raw.strip()
    for match in _FENCE.finditer(raw):
        yield match.group(1).strip()
    block = _balanced_block(raw)
    if block is not None:
        yield block


def _try_parse(text: str):
    for fixer in (lambda t: t, lambda t: _TRAILING_COMMAS.sub(r"\1", t)):
        try:
            data = json.loads(fixer(text))
        except (json.JSONDecodeError, RecursionError):
            continue
        if isinstance(data, (list, dict)):
            return data
    try:
        data = ast.literal_eval(text)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None
    return data if isinstance(data, (list, dict)) else None


def _balanced_block(text: str) -> str | None:
    """First quote-aware balanced [...] or {...} region."""
    for start, ch in enumerate(text):
        if ch not in "[{":
            continue
        end = _match_bracket(text, start)
        if end is not None:
            return text[start : end + 1]
    return None


def _match_bracket(text: str, start: int) -> int | None:
    pairs = {"[": "]", "{": "}"}
    closers = {"]", "}"}
    stack = [pairs[text[start]]]
    quote = None
    escaped = False
    for i in range(start + 1, len(text)):
        ch = text[i]
        if quote is not None:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in pairs:
            stack.append(pairs[ch])
        elif ch in closers:
            if ch != stack.pop():
                return None
            if not stack:
                return i
    return None
