"""Agent identity.

Benchmark runs use seeded neutral names — deterministic, variance-free, and
leak-proof. Demo runs may let agents pick names at tick 0; validation rejects
anything associable with a model provider, plus duplicates and junk.
"""
import re

from reco.engine.rng import permutation

NEUTRAL_NAMES = [
    "Alder", "Aspen", "Birch", "Briar", "Brook", "Cedar", "Cliff", "Clover",
    "Dell", "Dune", "Elm", "Ember", "Fern", "Flint", "Gale", "Grove",
    "Harbor", "Hazel", "Heath", "Iris", "Ivy", "Juniper", "Kestrel", "Knoll",
    "Lark", "Linden", "Maple", "Marsh", "Moss", "Nettle", "Oak", "Onyx",
    "Pine", "Quill", "Reed", "Ridge", "Rowan", "Sage", "Slate", "Sorrel",
    "Thorn", "Umber", "Vale", "Willow", "Wren", "Yarrow", "Zephyr",
]

BLOCKLIST = re.compile(
    r"claude|gpt|gemini|openai|anthropic|google|antigravity|sonnet|opus|haiku"
    r"|bard|llama|mistral|deepseek|grok|copilot|qwen|cohere|assistant|model"
    r"|\bai\b|[0-9]",
    re.IGNORECASE,
)

NAME_SHAPE = re.compile(r"^[A-Za-z][A-Za-z \-']{2,19}$")


def seeded_names(seed: int, agent_ids: list[str]) -> dict[str, str]:
    if len(agent_ids) > len(NEUTRAL_NAMES):
        raise ValueError(f"only {len(NEUTRAL_NAMES)} neutral names available")
    order = permutation(seed, len(NEUTRAL_NAMES), "names")
    return {
        agent: NEUTRAL_NAMES[order[i]]
        for i, agent in enumerate(sorted(agent_ids))
    }


def validate_display_name(name: str, taken: set[str]) -> str | None:
    """None if acceptable, else a human-readable reason."""
    if not NAME_SHAPE.match(name):
        return "name must be 3-20 letters (spaces, - and ' allowed), starting with a letter"
    if BLOCKLIST.search(name):
        return "name must not reference AI model providers or contain digits"
    if name.lower() in {t.lower() for t in taken}:
        return "name is already taken"
    return None
