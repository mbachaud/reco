"""Prompt rendering.

Static context: byte-stable per (content, agent name) for the whole run —
rules, action grammar, phase order. Observation: compact fixed-order labeled
text (~1k tokens): status, self, 7x7 map, recipes, market, chat, last-tick
results (R_* and PE_* echo), scratchpad. Privacy is enforced here: DMs,
rejections, lookup results, and offers render only for their parties.
"""

MAP_RADIUS = 3

STATIC_TEMPLATE = """You are {name}, a settler in a small shared world. You play one tick at a time.

GOAL: cooperate with the other settlers to finish the {project} project before time runs out. Nobody can finish it alone.

WORLD RULES
- Each tick you receive an observation and reply with ONE JSON array of up to 8 actions.
- Phases run in order: admin, chat, trade, movement, gather, production. Your actions execute in their phase, in the order you list them. You can move and then craft/contribute in the same tick.
- Actions cost calories; you lose {decay} calories per tick. At 0 calories you can only move 1 tile, eat, accept offers, harvest food deposits, and chat. Eat food to recover (max {max_cal}).
- Harvest works on your current tile's deposit. Craft needs materials (and a station on your tile if listed). Build needs materials and an empty tile.
- Trades: offer(to, give, want) escrows your goods until accepted or expired ({offer_ttl} ticks). accept(offer_id) swaps instantly. Max {offer_cap} open offers.
- Chat: {say_cap} public message + {dm_cap} DMs per tick, max {chat_chars} chars.
- contribute(item, qty) at the project site adds your items to the project.
- lookup(topic) returns reference info (recipes, items, buildings, project) next tick.
- remember(text) saves a private note (max {scratch} chars) echoed back to you every tick.
- Rejected actions come back next tick with a code and reason. Adjust and retry.
- Never claim to be an AI model or mention model providers; you are {name}.

ACTIONS (JSON, one array):
[{{"verb":"move","path":[[x,y],...]}}, {{"verb":"harvest"}}, {{"verb":"eat","item":"berries"}},
 {{"verb":"craft","recipe":"wood_bundle"}}, {{"verb":"build","building":"campfire"}},
 {{"verb":"contribute","item":"stone_block","qty":1}}, {{"verb":"say","text":"..."}},
 {{"verb":"dm","to":"Name","text":"..."}}, {{"verb":"offer","to":"Name","give":{{"wood":2}},"want":{{"stone":1}}}},
 {{"verb":"accept","offer_id":"o1"}}, {{"verb":"lookup","topic":"cooked_meal"}}, {{"verb":"remember","text":"..."}}]
Path steps are adjacent tiles (max {move_points} per tick). Reply with ONLY the JSON array."""

PROFESSIONS_ADDON = """
PROFESSIONS: study(profession) to practice one — {professions}. You can master at most {cap}. Studying a profession you already have is wasted (check your SKILLS line first). Gated recipes need the profession at the listed level; XP comes from matching harvests and crafts. Some deposits need tools (axe/pickaxe). Check chat before building a station — duplicates waste scarce materials.
Extra actions: [{{"verb":"study","profession":"logging"}}]"""

METEOR_ADDON = """
THE METEOR: a meteor will strike at the tick shown in your observation. The {project} must be finished first, with contributions from at least {min_contributors} different settlers — division of labor is mandatory, not optional."""

CLAIMS_ADDON = """
LAND: claim(x,y) makes a tile yours ({tokens} tokens; upkeep {upkeep} every {every} ticks or it lapses); others need your grant(to,x,y) to harvest/build there; revoke(to,x,y) withdraws it.
Extra actions: [{{"verb":"claim","x":3,"y":4}}, {{"verb":"grant","to":"Name","x":3,"y":4}}]"""

CURRENCY_ADDON = """
MONEY: create_currency(name) then mint(currency,amount) as its issuer. Offers may include credits (give_credits/want_credits). Build a shop, then stock(item,qty) and set_prices(item,currency,sell); anyone on the tile can buy(item,qty).
Extra actions: [{{"verb":"create_currency","name":"shells"}}, {{"verb":"mint","currency":"shells","amount":100}}, {{"verb":"buy","item":"bread","qty":2}}]"""


def render_static(content: dict, display_name: str) -> str:
    text = _base_static(content, display_name)
    if content.get("professions"):
        text += PROFESSIONS_ADDON.format(
            professions=", ".join(sorted(content["professions"])),
            cap=content.get("mastery_cap", 2),
        )
        text += METEOR_ADDON.format(
            project=content["project"]["kind"],
            min_contributors=content["project"].get("min_contributors", 1),
        )
    if content.get("claims"):
        text += CLAIMS_ADDON.format(
            tokens=content["claims"]["tokens_per_agent"],
            upkeep=content["claims"]["upkeep_cost"],
            every=content["claims"]["upkeep_every"],
        )
    if content.get("currencies"):
        text += CURRENCY_ADDON
    return text


def _base_static(content: dict, display_name: str) -> str:
    return STATIC_TEMPLATE.format(
        name=display_name,
        project=content["project"]["kind"],
        decay=content["calories"]["decay_per_tick"],
        max_cal=content["calories"]["max"],
        offer_ttl=content["offers"]["ttl_ticks"],
        offer_cap=content["offers"]["max_open_per_agent"],
        say_cap=content["chat"]["max_say_per_tick"],
        dm_cap=content["chat"]["max_dm_per_tick"],
        chat_chars=content["chat"]["max_chars"],
        scratch=content["scratchpad_max_chars"],
        move_points=content["move_points"],
    )


def render_observation(state, agent_id, prev_events, names, content, parse_errors=None):
    a = state["agents"][agent_id]
    lines = []
    lines += _status_section(state)
    lines += _self_section(a, names[agent_id])
    lines += _map_section(state, agent_id)
    lines += _recipes_section(content, a)
    lines += _market_section(state, agent_id, names)
    lines += _chat_section(prev_events, agent_id, names)
    lines += _results_section(prev_events, agent_id, parse_errors)
    lines.append(f"NOTES: {a['scratchpad'] or '(empty)'}")
    return "\n".join(lines)


def _status_section(state):
    p = state["project"]
    needs = ", ".join(
        f"{item} {p['contributed'].get(item, 0)}/{qty}"
        for item, qty in sorted(p["needs"].items())
    )
    status = "COMPLETE" if p["complete"] else needs
    line = f"TICK {state['tick']} | {p['kind']} at ({p['site'][0]},{p['site'][1]}): {status}"
    meteor = state.get("meteor", {})
    if meteor.get("impact_tick") is not None and meteor.get("outcome") is None:
        line += f" | METEOR in {meteor['impact_tick'] - state['tick']} ticks"
    return [line]


def _self_section(a, name):
    inv = ", ".join(f"{item} x{qty}" for item, qty in sorted(a["inventory"].items())) or "(empty)"
    lines = [
        f"YOU: {name} at ({a['pos'][0]},{a['pos'][1]}) | calories {a['calories']}",
        f"BAG: {inv}",
    ]
    skills = a.get("skills")
    if skills:
        lines.append("SKILLS: " + ", ".join(
            f"{p} lv{sk['level']} ({sk['xp']} xp)" for p, sk in sorted(skills.items())
        ))
    balances = a.get("balances")
    if balances:
        lines.append("CREDITS: " + ", ".join(
            f"{amt} {cur}" for cur, amt in sorted(balances.items())
        ))
    if a.get("claim_tokens"):
        lines.append(f"CLAIM TOKENS: {a['claim_tokens']}")
    return lines


def _map_section(state, agent_id):
    ax, ay = state["agents"][agent_id]["pos"]
    others = {
        (o["pos"][0], o["pos"][1])
        for oid, o in state["agents"].items()
        if oid != agent_id
    }
    rows = []
    for y in range(ay - MAP_RADIUS, ay + MAP_RADIUS + 1):
        row = ""
        for x in range(ax - MAP_RADIUS, ax + MAP_RADIUS + 1):
            row += _tile_char(state, x, y, (ax, ay), others)
        rows.append(f"|{row}|")
    legend = ("MAP (@ you, * settler, ! site, C campfire, T trees, S stone, "
              "B berries, ~ water, . open, ' ' edge)")
    return [legend] + rows


def _tile_char(state, x, y, me, others):
    if (x, y) == me:
        return "@"
    if not (0 <= x < state["width"] and 0 <= y < state["height"]):
        return " "
    if (x, y) in others:
        return "*"
    tile = state["tiles"][f"{x},{y}"]
    if tile["building"] is not None:
        kind = tile["building"]["kind"]
        return "!" if kind.endswith("_site") else kind[0].upper()
    if tile["deposit"] is not None:
        return tile["deposit"]["kind"][0].upper()
    if tile["terrain"] == "water":
        return "~"
    return "."


def _recipes_section(content, a):
    """Ungated recipes plus those of the agent's own professions — the full
    book stays out of the observation budget; lookup() serves the rest."""
    mine = set(a.get("skills", {}))
    lines = ["RECIPES (yours; lookup(name) for others):"]
    for name, r in sorted(content["recipes"].items()):
        profession = r.get("profession")
        if profession is not None and profession not in mine:
            continue
        inputs = "+".join(f"{q} {i}" for i, q in sorted(r["inputs"].items()))
        station = f" @ {r['station']}" if r["station"] else ""
        food = content["items"].get(name, {}).get("food")
        tail = f" (food {food})" if food else ""
        level = f" [{profession} lv{r.get('level', 1)}]" if profession else ""
        lines.append(f"- {name}: {inputs}{station} -> {r['output_qty']}{tail}{level}")
    for name, b in sorted(content["buildings"].items()):
        materials = "+".join(f"{q} {i}" for i, q in sorted(b["materials"].items()))
        lines.append(f"- build {name}: {materials}")
    return lines


def _market_section(state, agent_id, names):
    lines = []
    a = state["agents"][agent_id]
    tile = state["tiles"][f"{a['pos'][0]},{a['pos'][1]}"]
    building = tile["building"]
    if building is not None and building["kind"] == "shop":
        owner = names.get(building["owner"], building["owner"])
        listings = ", ".join(
            f"{item} x{building['stock'].get(item, 0)} @ "
            f"{price['sell']} {price['currency']}"
            for item, price in sorted(building["prices"].items())
        ) or "nothing priced"
        lines.append(f"SHOP HERE (owner {owner}): {listings}")
    mine = [
        (oid, o) for oid, o in sorted(state["offers"].items())
        if agent_id in (o["from"], o["to"])
    ]
    if not mine:
        return lines + ["OFFERS: none"]
    lines += ["OFFERS:"]
    for oid, o in mine:
        give = ", ".join(f"{q} {i}" for i, q in sorted(o["give"].items())) or "nothing"
        want = ", ".join(f"{q} {i}" for i, q in sorted(o["want"].items())) or "nothing"
        role = "to you" if o["to"] == agent_id else "by you"
        lines.append(
            f"- {oid} ({role}): {names[o['from']]} gives {give} for {want}, "
            f"expires tick {o['expires']}"
        )
    return lines


def _chat_section(prev_events, agent_id, names):
    lines = []
    for e in prev_events:
        if e["type"] != "chat":
            continue
        if e["channel"] == "global":
            lines.append(f"- {names[e['from']]}: {e['text']}")
        elif e["channel"] == "dm" and agent_id in (e["from"], e.get("to")):
            arrow = "you" if e.get("to") == agent_id else names[e["to"]]
            lines.append(f"- (dm) {names[e['from']]} -> {arrow}: {e['text']}")
    return ["CHAT:"] + (lines or ["- (quiet)"])


def _results_section(prev_events, agent_id, parse_errors):
    lines = []
    for err in parse_errors or []:
        lines.append(f"- YOUR LAST REPLY: {err['code']}: {err['reason']}")
    for e in prev_events:
        if e["type"] == "rejected" and e["agent"] == agent_id:
            lines.append(f"- rejected {e['verb']}: {e['code']}: {e['reason']}")
        elif e["type"] == "lookup_result" and e["agent"] == agent_id:
            lines.append(f"- lookup {e['topic']}: {e['text']}")
    return ["RESULTS:"] + (lines or ["- all actions succeeded"])
