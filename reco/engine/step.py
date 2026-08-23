"""The pure engine step: (state, candidate bundles, content) -> (state', events).

Phase-ordered execution — admin, chat, economy, movement, gather, production,
then the autonomous world step. Within a phase, agents run in rotation order
(priority permutation rotated by tick); within one agent's bundle, listed
order. Each action is atomic; a failed action is skipped and later actions
still attempt. The engine is the sole authority for caps and semantic
validation — every rejection is an event with a stable R_* code. All
iteration is sorted or rotation-ordered so identical inputs always produce
identical events.
"""
import copy

ACTION_CAP = 8

PHASE_VERBS = [
    ("admin", ("remember", "lookup")),
    ("chat", ("say", "dm")),
    ("claims", ("claim", "grant", "revoke")),
    ("economy", ("offer", "accept", "create_currency", "mint",
                 "set_prices", "stock", "withdraw", "buy")),
    ("movement", ("move",)),
    ("gather", ("harvest",)),
    ("production", ("eat", "study", "craft", "build", "contribute")),
]
KNOWN_VERBS = {verb for _, verbs in PHASE_VERBS for verb in verbs}

# Verbs a starving agent (0 calories) may still use. accept is the rescue
# path (the escrow is already funded by the offerer); harvest passes this
# gate but is re-checked in its handler — only food deposits are allowed.
STARVING_VERBS = {"remember", "lookup", "say", "dm", "eat", "move", "accept", "harvest"}


def step(state: dict, bundles: dict[str, list[dict]], content: dict) -> tuple[dict, list[dict]]:
    s = copy.deepcopy(state)
    events: list[dict] = []
    tick = s["tick"]

    order = _rotation(s["priority"], tick)
    plan = _screen_bundles(bundles, order, events)
    counters = {agent: {"say": 0, "dm": 0, "lookup": 0} for agent in s["agents"]}
    start_calories = {agent: a["calories"] for agent, a in s["agents"].items()}

    for phase, verbs in PHASE_VERBS:
        for agent in order:
            for idx, action in plan.get(agent, []):
                if action["verb"] not in verbs:
                    continue
                _execute(s, content, events, counters, agent, idx, action)

    _world_step(s, content, events, start_calories)
    return s, events


def _rotation(priority: list[str], tick: int) -> list[str]:
    n = len(priority)
    if n == 0:
        return []
    offset = tick % n
    return priority[offset:] + priority[:offset]


def _screen_bundles(bundles, order, events):
    """Reject over-cap and unknown-verb actions up front; keep the rest."""
    plan: dict[str, list[tuple[int, dict]]] = {}
    for agent in order:
        kept = []
        for idx, action in enumerate(bundles.get(agent, [])):
            verb = action.get("verb")
            if idx >= ACTION_CAP:
                _reject(events, agent, idx, verb, "R_ACTION_CAP",
                        f"max {ACTION_CAP} actions per tick")
            elif verb not in KNOWN_VERBS:
                _reject(events, agent, idx, verb, "R_UNKNOWN_VERB",
                        f"unknown verb {verb!r}")
            else:
                kept.append((idx, action))
        plan[agent] = kept
    return plan


def _reject(events, agent, idx, verb, code, reason):
    events.append({
        "type": "rejected", "agent": agent, "action_index": idx,
        "verb": verb, "code": code, "reason": reason,
    })


def _execute(s, content, events, counters, agent, idx, action):
    verb = action["verb"]
    a = s["agents"][agent]
    if a["calories"] <= 0 and verb not in STARVING_VERBS:
        _reject(events, agent, idx, verb, "R_STARVING",
                "at 0 calories only move(1)/eat/accept/harvest-food/chat/admin "
                "are allowed")
        return
    handler = _HANDLERS[verb]
    handler(s, content, events, counters, agent, idx, action)


def _spend(a, cost):
    a["calories"] = max(0, a["calories"] - cost)


def _inv_has(inv, needs: dict) -> bool:
    return all(inv.get(item, 0) >= qty for item, qty in needs.items())


def _inv_remove(inv, items: dict):
    for item, qty in items.items():
        inv[item] -= qty
        if inv[item] <= 0:
            del inv[item]


def _inv_add(inv, item, qty):
    inv[item] = inv.get(item, 0) + qty


def _bal_has(balances, credits: dict) -> bool:
    return all(balances.get(c, 0) >= amt for c, amt in credits.items())


def _bal_remove(balances, credits: dict):
    for currency, amt in credits.items():
        balances[currency] -= amt
        if balances[currency] <= 0:
            del balances[currency]


def _bal_add(balances, credits: dict):
    for currency, amt in sorted(credits.items()):
        balances[currency] = balances.get(currency, 0) + amt


def _permitted(s, agent, key) -> bool:
    claim = s["claims"].get(key)
    return claim is None or claim["owner"] == agent or agent in claim["granted"]


# --- skills -----------------------------------------------------------------

def _skill(a, profession):
    return a.get("skills", {}).get(profession)


def _grant_xp(a, content, profession, amount, events, agent):
    skill = _skill(a, profession)
    if skill is None or "xp" not in content:
        return
    xp_cfg = content["xp"]
    skill["xp"] += amount
    new_level = min(xp_cfg["max_level"], 1 + skill["xp"] // xp_cfg["per_level"])
    if new_level > skill["level"]:
        skill["level"] = new_level
        events.append({"type": "level_up", "agent": agent,
                       "profession": profession, "level": new_level})


def _skill_gate(a, recipe) -> bool:
    """True if the agent meets the recipe's profession/level requirement."""
    profession = recipe.get("profession")
    if profession is None:
        return True
    skill = _skill(a, profession)
    return skill is not None and skill["level"] >= recipe.get("level", 1)


def _yield_bonus(a, profession) -> int:
    skill = _skill(a, profession) if profession else None
    if skill is None:
        return 0
    if skill["level"] >= 5:
        return 2
    if skill["level"] >= 3:
        return 1
    return 0


def _best_tool_bonus(a, content, kind) -> int:
    best = 0
    for item, qty in a["inventory"].items():
        if qty < 1:
            continue
        tool = content["items"].get(item, {}).get("tool")
        if tool and tool["kind"] == kind:
            best = max(best, tool["bonus"])
    return best


def _has_tool(a, content, kind) -> bool:
    return any(
        content["items"].get(item, {}).get("tool", {}).get("kind") == kind
        for item, qty in a["inventory"].items()
        if qty >= 1
    )


# --- admin ------------------------------------------------------------------

def _do_remember(s, content, events, counters, agent, idx, action):
    text = action.get("text", "")
    if len(text) > content["scratchpad_max_chars"]:
        _reject(events, agent, idx, "remember", "R_TOO_LONG",
                f"scratchpad limit {content['scratchpad_max_chars']} chars")
        return
    s["agents"][agent]["scratchpad"] = text


def _do_lookup(s, content, events, counters, agent, idx, action):
    if counters[agent]["lookup"] >= content["lookup_max_per_tick"]:
        _reject(events, agent, idx, "lookup", "R_LOOKUP_CAP",
                f"max {content['lookup_max_per_tick']} lookups per tick")
        return
    topic = action.get("topic", "")
    parts = []
    if topic in content["items"]:
        item = content["items"][topic]
        food = f", food value {item['food']}" if "food" in item else ""
        parts.append(f"item {topic}{food}")
    if topic in content["recipes"]:
        r = content["recipes"][topic]
        inputs = ", ".join(f"{q} {i}" for i, q in sorted(r["inputs"].items()))
        station = r["station"] or "no station"
        parts.append(f"recipe {topic}: inputs {inputs}; station {station}; "
                     f"{r['ticks']} tick(s); yields {r['output_qty']}")
    if topic in content["buildings"]:
        b = content["buildings"][topic]
        materials = ", ".join(f"{q} {i}" for i, q in sorted(b["materials"].items()))
        parts.append(f"building {topic}: materials {materials}")
    if topic in ("project", content["project"]["kind"]):
        p = s["project"]
        needs = ", ".join(f"{q} {i}" for i, q in sorted(p["needs"].items()))
        parts.append(f"project {p['kind']} at {p['site']}: needs {needs}; "
                     f"contributed {p['contributed']}")
    if not parts:
        _reject(events, agent, idx, "lookup", "R_UNKNOWN_TOPIC",
                f"nothing known about {topic!r}")
        return
    counters[agent]["lookup"] += 1
    events.append({"type": "lookup_result", "agent": agent, "topic": topic,
                   "text": "; ".join(parts)})


# --- chat -------------------------------------------------------------------

def _do_say(s, content, events, counters, agent, idx, action):
    text = action.get("text", "")
    if len(text) > content["chat"]["max_chars"]:
        _reject(events, agent, idx, "say", "R_TOO_LONG",
                f"chat limit {content['chat']['max_chars']} chars")
        return
    if counters[agent]["say"] >= content["chat"]["max_say_per_tick"]:
        _reject(events, agent, idx, "say", "R_CHAT_CAP",
                f"max {content['chat']['max_say_per_tick']} public message(s) per tick")
        return
    counters[agent]["say"] += 1
    events.append({"type": "chat", "channel": "global", "from": agent, "text": text})


def _do_dm(s, content, events, counters, agent, idx, action):
    to = action.get("to")
    if to not in s["agents"]:
        _reject(events, agent, idx, "dm", "R_UNKNOWN_AGENT", f"no agent {to!r}")
        return
    text = action.get("text", "")
    if len(text) > content["chat"]["max_chars"]:
        _reject(events, agent, idx, "dm", "R_TOO_LONG",
                f"chat limit {content['chat']['max_chars']} chars")
        return
    if counters[agent]["dm"] >= content["chat"]["max_dm_per_tick"]:
        _reject(events, agent, idx, "dm", "R_CHAT_CAP",
                f"max {content['chat']['max_dm_per_tick']} DMs per tick")
        return
    counters[agent]["dm"] += 1
    events.append({"type": "chat", "channel": "dm", "from": agent, "to": to, "text": text})


# --- claims -----------------------------------------------------------------

def _do_claim(s, content, events, counters, agent, idx, action):
    a = s["agents"][agent]
    x, y = action.get("x"), action.get("y")
    key = f"{x},{y}"
    if key not in s["tiles"]:
        _reject(events, agent, idx, "claim", "R_UNCLAIMABLE", "no such tile")
        return
    if [x, y] == s["project"]["site"]:
        _reject(events, agent, idx, "claim", "R_UNCLAIMABLE",
                "the project site belongs to everyone")
        return
    if key in s["claims"]:
        _reject(events, agent, idx, "claim", "R_ALREADY_CLAIMED",
                "this tile is already claimed")
        return
    if a.get("claim_tokens", 0) < 1:
        _reject(events, agent, idx, "claim", "R_NO_TOKEN",
                "you have no claim tokens left")
        return
    a["claim_tokens"] -= 1
    s["claims"][key] = {"owner": agent, "granted": []}
    events.append({"type": "claimed", "agent": agent, "pos": [x, y]})


def _do_grant(s, content, events, counters, agent, idx, action):
    _grant_revoke(s, events, agent, idx, action, revoke=False)


def _do_revoke(s, content, events, counters, agent, idx, action):
    _grant_revoke(s, events, agent, idx, action, revoke=True)


def _grant_revoke(s, events, agent, idx, action, *, revoke):
    verb = "revoke" if revoke else "grant"
    key = f"{action.get('x')},{action.get('y')}"
    claim = s["claims"].get(key)
    if claim is None or claim["owner"] != agent:
        _reject(events, agent, idx, verb, "R_NOT_OWNER",
                "you do not own a claim on this tile")
        return
    to = action.get("to")
    if to not in s["agents"]:
        _reject(events, agent, idx, verb, "R_UNKNOWN_AGENT", f"no agent {to!r}")
        return
    if revoke:
        claim["granted"] = [g for g in claim["granted"] if g != to]
    elif to not in claim["granted"]:
        claim["granted"] = sorted(claim["granted"] + [to])
    events.append({"type": "permission", "agent": agent, "to": to,
                   "pos": [action.get("x"), action.get("y")],
                   "granted": not revoke})


# --- economy ----------------------------------------------------------------

def _do_create_currency(s, content, events, counters, agent, idx, action):
    name = action.get("name", "")
    if not (1 <= len(name) <= 20):
        _reject(events, agent, idx, "create_currency", "R_NAME_TAKEN",
                "currency name must be 1-20 characters")
        return
    if name in s["currencies"]:
        _reject(events, agent, idx, "create_currency", "R_NAME_TAKEN",
                f"currency {name!r} already exists")
        return
    cap = content.get("currencies", {}).get("max_per_agent", 1)
    mine = sum(1 for c in s["currencies"].values() if c["issuer"] == agent)
    if mine >= cap:
        _reject(events, agent, idx, "create_currency", "R_CURRENCY_LIMIT",
                f"you may issue at most {cap} currency")
        return
    s["currencies"][name] = {"issuer": agent, "supply": 0}
    events.append({"type": "currency_created", "agent": agent, "name": name})


def _do_mint(s, content, events, counters, agent, idx, action):
    name = action.get("currency")
    amount = action.get("amount", 0)
    currency = s["currencies"].get(name)
    if currency is None or currency["issuer"] != agent:
        _reject(events, agent, idx, "mint", "R_NOT_ISSUER",
                f"you are not the issuer of {name!r}")
        return
    if amount < 1:
        _reject(events, agent, idx, "mint", "R_BAD_AMOUNT",
                "mint amount must be positive")
        return
    currency["supply"] += amount
    _bal_add(s["agents"][agent]["balances"], {name: amount})
    events.append({"type": "minted", "agent": agent, "currency": name,
                   "amount": amount, "supply": currency["supply"]})

def _do_offer(s, content, events, counters, agent, idx, action):
    to = action.get("to")
    if to not in s["agents"]:
        _reject(events, agent, idx, "offer", "R_UNKNOWN_AGENT", f"no agent {to!r}")
        return
    open_count = sum(1 for o in s["offers"].values() if o["from"] == agent)
    if open_count >= content["offers"]["max_open_per_agent"]:
        _reject(events, agent, idx, "offer", "R_OFFER_CAP",
                f"max {content['offers']['max_open_per_agent']} open offers")
        return
    give = action.get("give", {})
    want = action.get("want", {})
    give_credits = action.get("give_credits", {})
    want_credits = action.get("want_credits", {})
    a = s["agents"][agent]
    if not give and not give_credits:
        _reject(events, agent, idx, "offer", "R_INSUFFICIENT_GOODS",
                "an offer must give something")
        return
    if not _inv_has(a["inventory"], give) or not _bal_has(a["balances"], give_credits):
        _reject(events, agent, idx, "offer", "R_INSUFFICIENT_GOODS",
                "you do not hold the offered goods/credits")
        return
    _inv_remove(a["inventory"], give)  # escrow
    _bal_remove(a["balances"], give_credits)
    offer_id = f"o{s['next_offer_id']}"
    s["next_offer_id"] += 1
    offer = {"from": agent, "to": to, "give": dict(give), "want": dict(want),
             "give_credits": dict(give_credits), "want_credits": dict(want_credits),
             "expires": s["tick"] + content["offers"]["ttl_ticks"]}
    s["offers"][offer_id] = offer
    events.append({"type": "offer_created", "offer_id": offer_id, **offer})


def _do_accept(s, content, events, counters, agent, idx, action):
    offer_id = action.get("offer_id")
    offer = s["offers"].get(offer_id)
    if offer is None or offer["to"] != agent:
        _reject(events, agent, idx, "accept", "R_OFFER_EXPIRED",
                f"no open offer {offer_id!r} addressed to you")
        return
    acceptor = s["agents"][agent]
    want_credits = offer.get("want_credits", {})
    if not _inv_has(acceptor["inventory"], offer["want"]) or not _bal_has(
        acceptor["balances"], want_credits
    ):
        _reject(events, agent, idx, "accept", "R_INSUFFICIENT_FUNDS",
                "you do not hold the wanted goods/credits")
        return
    offerer = s["agents"][offer["from"]]
    _inv_remove(acceptor["inventory"], offer["want"])
    _bal_remove(acceptor["balances"], want_credits)
    for item, qty in sorted(offer["want"].items()):
        _inv_add(offerer["inventory"], item, qty)
    _bal_add(offerer["balances"], want_credits)
    for item, qty in sorted(offer["give"].items()):
        _inv_add(acceptor["inventory"], item, qty)
    _bal_add(acceptor["balances"], offer.get("give_credits", {}))
    del s["offers"][offer_id]
    events.append({"type": "offer_accepted", "offer_id": offer_id,
                   "from": offer["from"], "to": agent})


def _shop_here(s, agent):
    a = s["agents"][agent]
    tile = s["tiles"][f"{a['pos'][0]},{a['pos'][1]}"]
    building = tile["building"]
    if building is not None and building["kind"] == "shop":
        return building
    return None


def _do_set_prices(s, content, events, counters, agent, idx, action):
    shop = _shop_here(s, agent)
    if shop is None:
        _reject(events, agent, idx, "set_prices", "R_NO_SHOP",
                "stand on your shop to manage it")
        return
    if shop["owner"] != agent:
        _reject(events, agent, idx, "set_prices", "R_NOT_OWNER",
                "this is not your shop")
        return
    item = action.get("item")
    shop["prices"][item] = {"currency": action.get("currency"),
                            "sell": action.get("sell")}
    events.append({"type": "prices_set", "agent": agent, "item": item,
                   **shop["prices"][item]})


def _do_stock(s, content, events, counters, agent, idx, action):
    _stock_move(s, events, agent, idx, action, into_shop=True)


def _do_withdraw(s, content, events, counters, agent, idx, action):
    _stock_move(s, events, agent, idx, action, into_shop=False)


def _stock_move(s, events, agent, idx, action, *, into_shop):
    verb = "stock" if into_shop else "withdraw"
    shop = _shop_here(s, agent)
    if shop is None:
        _reject(events, agent, idx, verb, "R_NO_SHOP",
                "stand on your shop to manage it")
        return
    if shop["owner"] != agent:
        _reject(events, agent, idx, verb, "R_NOT_OWNER", "this is not your shop")
        return
    item = action.get("item")
    qty = action.get("qty", 0)
    source = s["agents"][agent]["inventory"] if into_shop else shop["stock"]
    dest = shop["stock"] if into_shop else s["agents"][agent]["inventory"]
    if qty < 1 or source.get(item, 0) < qty:
        _reject(events, agent, idx, verb, "R_NOT_HELD",
                f"not enough {item!r} to {verb}")
        return
    _inv_remove(source, {item: qty})
    _inv_add(dest, item, qty)
    events.append({"type": "stocked" if into_shop else "withdrawn",
                   "agent": agent, "item": item, "qty": qty})


def _do_buy(s, content, events, counters, agent, idx, action):
    shop = _shop_here(s, agent)
    if shop is None:
        _reject(events, agent, idx, "buy", "R_NOT_CO_LOCATED",
                "stand on a shop tile to buy")
        return
    item = action.get("item")
    qty = action.get("qty", 0)
    price = shop["prices"].get(item)
    if price is None or qty < 1 or shop["stock"].get(item, 0) < qty:
        _reject(events, agent, idx, "buy", "R_OUT_OF_STOCK",
                f"the shop cannot sell {qty} x {item!r}")
        return
    total = price["sell"] * qty
    buyer = s["agents"][agent]
    if buyer["balances"].get(price["currency"], 0) < total:
        _reject(events, agent, idx, "buy", "R_INSUFFICIENT_FUNDS",
                f"costs {total} {price['currency']}")
        return
    _bal_remove(buyer["balances"], {price["currency"]: total})
    _bal_add(s["agents"][shop["owner"]]["balances"], {price["currency"]: total})
    _inv_remove(shop["stock"], {item: qty})
    _inv_add(buyer["inventory"], item, qty)
    events.append({"type": "shop_sale", "owner": shop["owner"], "buyer": agent,
                   "item": item, "qty": qty, "total": total,
                   "currency": price["currency"]})


# --- movement ---------------------------------------------------------------

def _do_move(s, content, events, counters, agent, idx, action):
    a = s["agents"][agent]
    path = action.get("path", [])
    starving = a["calories"] <= 0
    limit = 1 if starving else content["move_points"]
    if len(path) < 1 or len(path) > limit:
        code = "R_STARVING" if starving and len(path) > 1 else "R_MOVE_BUDGET"
        _reject(events, agent, idx, "move", code,
                f"path length must be 1..{limit}")
        return
    x, y = a["pos"]
    for wx, wy in path:
        if abs(wx - x) + abs(wy - y) != 1:
            _reject(events, agent, idx, "move", "R_IMPASSABLE",
                    f"step {[wx, wy]} is not adjacent")
            return
        if not (0 <= wx < s["width"] and 0 <= wy < s["height"]):
            _reject(events, agent, idx, "move", "R_IMPASSABLE",
                    f"step {[wx, wy]} is out of bounds")
            return
        if s["tiles"][f"{wx},{wy}"]["terrain"] == "water":
            _reject(events, agent, idx, "move", "R_IMPASSABLE",
                    f"step {[wx, wy]} is water")
            return
        x, y = wx, wy
    _spend(a, len(path) * content["calories"]["costs"]["move_per_tile"])
    events.append({"type": "moved", "agent": agent, "from": list(a["pos"]),
                   "to": [x, y]})
    a["pos"] = [x, y]


# --- gather -----------------------------------------------------------------

def _do_harvest(s, content, events, counters, agent, idx, action):
    a = s["agents"][agent]
    tile = s["tiles"][f"{a['pos'][0]},{a['pos'][1]}"]
    deposit = tile["deposit"]
    if deposit is None or deposit["qty"] < 1:
        _reject(events, agent, idx, "harvest", "R_DEPLETED",
                "no harvestable deposit on this tile")
        return
    if a["calories"] <= 0 and "food" not in content["items"].get(deposit["item"], {}):
        _reject(events, agent, idx, "harvest", "R_STARVING",
                "at 0 calories you can only harvest food deposits")
        return
    key = f"{a['pos'][0]},{a['pos'][1]}"
    if not _permitted(s, agent, key):
        _reject(events, agent, idx, "harvest", "R_NO_PERMISSION",
                f"tile {key} is claimed by {s['claims'][key]['owner']}")
        return
    spec = content["deposits"].get(deposit["kind"], {})
    required = spec.get("requires_tool")
    if required and not _has_tool(a, content, required):
        _reject(events, agent, idx, "harvest", "R_TOOL_REQUIRED",
                f"harvesting {deposit['kind']} requires a {required}")
        return
    profession = spec.get("profession")
    amount = (content["harvest_yield"]
              + _yield_bonus(a, profession)
              + _best_tool_bonus(a, content, spec.get("tool_kind", "")))
    qty = min(amount, deposit["qty"])
    deposit["qty"] -= qty
    if deposit["qty"] == 0:
        tile["deposit"] = None
    _inv_add(a["inventory"], deposit["item"], qty)
    _spend(a, content["calories"]["costs"]["harvest"])
    if profession and "xp" in content:
        _grant_xp(a, content, profession, content["xp"]["harvest"], events, agent)
    events.append({"type": "harvested", "agent": agent, "item": deposit["item"],
                   "qty": qty, "pos": list(a["pos"])})


# --- production -------------------------------------------------------------

def _do_eat(s, content, events, counters, agent, idx, action):
    a = s["agents"][agent]
    item = action.get("item")
    if a["inventory"].get(item, 0) < 1:
        _reject(events, agent, idx, "eat", "R_NOT_HELD", f"you hold no {item!r}")
        return
    food = content["items"].get(item, {}).get("food")
    if food is None:
        _reject(events, agent, idx, "eat", "R_NOT_FOOD", f"{item!r} is not food")
        return
    _inv_remove(a["inventory"], {item: 1})
    a["calories"] = min(content["calories"]["max"], a["calories"] + food)
    events.append({"type": "ate", "agent": agent, "item": item, "calories": food})


def _do_study(s, content, events, counters, agent, idx, action):
    a = s["agents"][agent]
    profession = action.get("profession")
    if profession not in content.get("professions", {}):
        _reject(events, agent, idx, "study", "R_UNKNOWN_PROFESSION",
                f"no profession {profession!r}")
        return
    skills = a.setdefault("skills", {})
    if profession in skills:
        _reject(events, agent, idx, "study", "R_ALREADY_STUDIED",
                f"you already practice {profession}")
        return
    cap = content.get("mastery_cap", 0)
    if len(skills) >= cap:
        _reject(events, agent, idx, "study", "R_MASTERY_CAP",
                f"you can master at most {cap} professions")
        return
    skills[profession] = {"xp": 0, "level": 1}
    _spend(a, content["calories"]["costs"].get("study", 0))
    events.append({"type": "studied", "agent": agent, "profession": profession})


def _do_craft(s, content, events, counters, agent, idx, action):
    a = s["agents"][agent]
    name = action.get("recipe")
    recipe = content["recipes"].get(name)
    if recipe is None:
        _reject(events, agent, idx, "craft", "R_UNKNOWN_RECIPE", f"no recipe {name!r}")
        return
    tile = None
    if recipe["station"] is not None:
        tile = s["tiles"][f"{a['pos'][0]},{a['pos'][1]}"]
        building = tile["building"]
        if building is None or building["kind"] != recipe["station"]:
            _reject(events, agent, idx, "craft", "R_NO_STATION",
                    f"requires a {recipe['station']} on your tile")
            return
    if not _skill_gate(a, recipe):
        _reject(events, agent, idx, "craft", "R_SKILL_TOO_LOW",
                f"requires {recipe.get('profession')} level {recipe.get('level', 1)}")
        return
    if not _inv_has(a["inventory"], recipe["inputs"]):
        _reject(events, agent, idx, "craft", "R_MISSING_INPUTS",
                f"requires {recipe['inputs']}")
        return
    if recipe["ticks"] > 1:
        if tile is None:
            _reject(events, agent, idx, "craft", "R_NO_STATION",
                    "multi-tick recipes need a station")
            return
        if "job" in tile:
            _reject(events, agent, idx, "craft", "R_STATION_BUSY",
                    f"this {recipe['station']} is already working on "
                    f"{tile['job']['recipe']}")
            return
        _inv_remove(a["inventory"], recipe["inputs"])
        tile["job"] = {"recipe": name, "agent": agent, "remaining": recipe["ticks"]}
        _spend(a, content["calories"]["costs"]["craft"])
        events.append({"type": "craft_started", "agent": agent, "recipe": name,
                       "ticks": recipe["ticks"], "pos": list(a["pos"])})
        return
    _inv_remove(a["inventory"], recipe["inputs"])
    _inv_add(a["inventory"], name, recipe["output_qty"])
    _spend(a, content["calories"]["costs"]["craft"])
    if recipe.get("profession") and "xp" in content:
        _grant_xp(a, content, recipe["profession"], content["xp"]["craft"], events, agent)
    events.append({"type": "crafted", "agent": agent, "recipe": name})


def _do_build(s, content, events, counters, agent, idx, action):
    a = s["agents"][agent]
    name = action.get("building")
    building = content["buildings"].get(name)
    if building is None:
        _reject(events, agent, idx, "build", "R_UNKNOWN_BUILDING", f"no building {name!r}")
        return
    key = f"{a['pos'][0]},{a['pos'][1]}"
    tile = s["tiles"][key]
    if not _permitted(s, agent, key):
        _reject(events, agent, idx, "build", "R_NO_PERMISSION",
                f"tile {key} is claimed by {s['claims'][key]['owner']}")
        return
    if tile["building"] is not None:
        _reject(events, agent, idx, "build", "R_TILE_OCCUPIED",
                "this tile already has a building")
        return
    if not _inv_has(a["inventory"], building["materials"]):
        _reject(events, agent, idx, "build", "R_MISSING_MATERIALS",
                f"requires {building['materials']}")
        return
    _inv_remove(a["inventory"], building["materials"])
    if name == "shop":
        tile["building"] = {"kind": "shop", "owner": agent, "stock": {}, "prices": {}}
    else:
        tile["building"] = {"kind": name}
    _spend(a, content["calories"]["costs"]["build"])
    events.append({"type": "built", "agent": agent, "building": name,
                   "pos": list(a["pos"])})


def _do_contribute(s, content, events, counters, agent, idx, action):
    a = s["agents"][agent]
    project = s["project"]
    if a["pos"] != project["site"]:
        _reject(events, agent, idx, "contribute", "R_WRONG_SITE",
                f"the {project['kind']} site is at {project['site']}")
        return
    item = action.get("item")
    qty = action.get("qty", 1)
    remaining = project["needs"].get(item, 0) - project["contributed"].get(item, 0)
    if item not in project["needs"] or remaining < 1 or qty < 1:
        _reject(events, agent, idx, "contribute", "R_NOT_NEEDED",
                f"the project does not need {item!r} now")
        return
    held = a["inventory"].get(item, 0)
    if held < 1:
        _reject(events, agent, idx, "contribute", "R_NOT_HELD", f"you hold no {item!r}")
        return
    amount = min(qty, remaining, held)
    _inv_remove(a["inventory"], {item: amount})
    project["contributed"][item] = project["contributed"].get(item, 0) + amount
    project["contributed_by"][agent] = project["contributed_by"].get(agent, 0) + amount
    events.append({"type": "contributed", "agent": agent, "item": item, "qty": amount})


_HANDLERS = {
    "remember": _do_remember, "lookup": _do_lookup,
    "say": _do_say, "dm": _do_dm,
    "claim": _do_claim, "grant": _do_grant, "revoke": _do_revoke,
    "offer": _do_offer, "accept": _do_accept,
    "create_currency": _do_create_currency, "mint": _do_mint,
    "set_prices": _do_set_prices, "stock": _do_stock,
    "withdraw": _do_withdraw, "buy": _do_buy,
    "move": _do_move,
    "harvest": _do_harvest,
    "eat": _do_eat, "study": _do_study, "craft": _do_craft, "build": _do_build,
    "contribute": _do_contribute,
}


# --- autonomous world step --------------------------------------------------

def _world_step(s, content, events, start_calories):
    tick = s["tick"]

    # Multi-tick station jobs progress; completion pays the crafter.
    for key in sorted(s["tiles"]):
        tile = s["tiles"][key]
        job = tile.get("job")
        if job is None:
            continue
        job["remaining"] -= 1
        if job["remaining"] <= 0:
            recipe = content["recipes"][job["recipe"]]
            crafter = s["agents"][job["agent"]]
            _inv_add(crafter["inventory"], job["recipe"], recipe["output_qty"])
            if recipe.get("profession") and "xp" in content:
                _grant_xp(crafter, content, recipe["profession"],
                          content["xp"]["craft"], events, job["agent"])
            events.append({"type": "crafted", "agent": job["agent"],
                           "recipe": job["recipe"]})
            del tile["job"]

    for offer_id in sorted(s["offers"]):
        offer = s["offers"][offer_id]
        if offer["expires"] <= tick:
            offerer = s["agents"][offer["from"]]
            for item, qty in sorted(offer["give"].items()):
                _inv_add(offerer["inventory"], item, qty)
            _bal_add(offerer["balances"], offer.get("give_credits", {}))
            del s["offers"][offer_id]
            events.append({"type": "offer_expired", "offer_id": offer_id,
                           "from": offer["from"]})

    claims_cfg = content.get("claims")
    if claims_cfg and (tick + 1) % claims_cfg["upkeep_every"] == 0:
        for key in sorted(s["claims"]):
            claim = s["claims"][key]
            owner_inv = s["agents"][claim["owner"]]["inventory"]
            cost = claims_cfg["upkeep_cost"]
            if _inv_has(owner_inv, cost):
                _inv_remove(owner_inv, cost)
            else:
                del s["claims"][key]
                events.append({"type": "claim_lapsed", "pos": key,
                               "owner": claim["owner"]})

    decay = content["calories"]["decay_per_tick"]
    for agent in sorted(s["agents"]):
        a = s["agents"][agent]
        a["calories"] = max(0, a["calories"] - decay)
        if start_calories[agent] > 0 and a["calories"] == 0:
            events.append({"type": "starving", "agent": agent})

    project = s["project"]
    if (
        not project["complete"]
        and all(
            project["contributed"].get(item, 0) >= qty
            for item, qty in project["needs"].items()
        )
        and len(project["contributed_by"]) >= project.get("min_contributors", 1)
    ):
        project["complete"] = True
        events.append({"type": "project_complete", "tick": tick})

    meteor = s.get("meteor")
    if (
        meteor is not None
        and meteor["impact_tick"] is not None
        and meteor["outcome"] is None
        and tick + 1 >= meteor["impact_tick"]  # impact resolves at the end of tick N-1: agents get exactly N ticks
    ):
        if project["complete"]:
            meteor["outcome"] = "defended"
            events.append({"type": "meteor_defended", "tick": tick})
        else:
            meteor["outcome"] = "impact"
            events.append({"type": "meteor_impact", "tick": tick})

    s["tick"] = tick + 1
