"""Deterministic map generation and initial state.

Zone layout (slice): forest NW quadrant, mountain NE quadrant, plains south
half, a few keyed-random water ponds in the plains, Beacon project site at the
exact center. Spawn anchors sit inside each zone so pilot agents start
adjacent to exactly one resource type. Every random choice is a keyed-hash
draw — the whole state is a pure function of (seed, content, agent_ids).
"""
from reco.engine.rng import permutation, rand_below

WATER_PONDS = 4


def _zone_terrain(x: int, y: int, width: int, height: int) -> str:
    if y < height // 2:
        return "forest" if x < width // 2 else "mountain"
    return "plains"


def _deposit_options(terrain: str, content: dict) -> list[str]:
    return sorted(
        kind for kind, deposit in content["deposits"].items()
        if deposit["terrain"] == terrain
    )


def init_state(*, seed: int, content: dict, agent_ids: list[str], width: int = 12,
               height: int = 12, meteor_tick: int | None = None) -> dict:
    center = [width // 2, height // 2]
    tiles: dict[str, dict] = {}
    for y in range(height):
        for x in range(width):
            terrain = _zone_terrain(x, y, width, height)
            tile = {"terrain": terrain, "deposit": None, "building": None}
            options = _deposit_options(terrain, content)
            if options and rand_below(seed, 3, "has_deposit", x, y) < 2:
                kind = options[rand_below(seed, len(options), "deposit_kind", x, y)]
                spec = content["deposits"][kind]
                span = spec["qty_max"] - spec["qty_min"] + 1
                qty = spec["qty_min"] + rand_below(seed, span, "deposit_qty", x, y)
                tile["deposit"] = {"kind": kind, "item": spec["yields"], "qty": qty}
            tiles[f"{x},{y}"] = tile

    # Water ponds in the plains (never on the center or spawn anchors).
    anchors = _spawn_anchors(width, height)
    reserved = {f"{center[0]},{center[1]}"} | {f"{x},{y}" for x, y in anchors.values()}
    for i in range(WATER_PONDS):
        x = rand_below(seed, width, "water", i, "x")
        y = height // 2 + rand_below(seed, height - height // 2, "water", i, "y")
        key = f"{x},{y}"
        if key not in reserved and tiles[key]["terrain"] == "plains":
            tiles[key] = {"terrain": "water", "deposit": None, "building": None}

    # Beacon site: cleared center tile.
    tiles[f"{center[0]},{center[1]}"] = {
        "terrain": "plains",
        "deposit": None,
        "building": {"kind": "beacon_site"},
    }

    zone_order = ["forest", "mountain", "plains"]
    agents = {}
    for i, agent_id in enumerate(agent_ids):
        zone = zone_order[i % len(zone_order)]
        ax, ay = anchors[zone]
        ax += i // len(zone_order)  # extra agents in a zone fan out east
        agents[agent_id] = {
            "pos": [ax, ay],
            "calories": content["calories"]["start"],
            "inventory": {},
            "balances": {},
            "claim_tokens": content.get("claims", {}).get("tokens_per_agent", 0),
            "scratchpad": "",
        }

    order = permutation(seed, len(agent_ids), "priority")
    priority = [sorted(agent_ids)[i] for i in order]

    return {
        "tick": 0,
        "seed": seed,
        "width": width,
        "height": height,
        "tiles": tiles,
        "agents": agents,
        "priority": priority,
        "offers": {},
        "next_offer_id": 1,
        "currencies": {},
        "claims": {},
        "project": {
            "kind": content["project"]["kind"],
            "site": center,
            "needs": dict(content["project"]["needs"]),
            "contributed": {},
            "contributed_by": {},
            "min_contributors": content["project"].get("min_contributors", 1),
            "complete": False,
        },
        "meteor": {"impact_tick": meteor_tick, "outcome": None},
        "content_hash": content["content_hash"],
    }


def _spawn_anchors(width: int, height: int) -> dict[str, tuple[int, int]]:
    return {
        "forest": (width // 4, height // 4),
        "mountain": (3 * width // 4, height // 4),
        "plains": (width // 4, 3 * height // 4),
    }
