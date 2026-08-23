"""Scripted bot policies: deterministic pure functions of the full state.

These are the zero-quota drivers — used for engine development, fuzzing, and
later as benchmark baselines. `greedy` roles (wood/stone/meal) cooperate to
complete the Beacon: gatherers deliver their component then gift materials to
the meal bot, which builds a campfire beside the site, cooks, and delivers.
`random` is a fuzzing walker.
"""
from reco.engine.rng import rand_below

GATHERER_SPECS = {
    "wood": {"deposit": "trees", "base": "wood", "component": "wood_bundle",
             "gift": {"wood": 2}},
    "stone": {"deposit": "stone_outcrop", "base": "stone", "component": "stone_block",
              "gift": {"stone": 1}},
}


def decide_scripted(state, agent_id, role, content, roles=None):
    if role in GATHERER_SPECS:
        return _gatherer(state, agent_id, GATHERER_SPECS[role], content, roles)
    if role == "meal":
        return _meal(state, agent_id, content)
    if role == "provisioner":
        return _provisioner(state, agent_id, content)
    if role == "random":
        return _random_bot(state, agent_id, content)
    raise ValueError(f"unknown scripted role {role!r}")


# --- shared helpers ---------------------------------------------------------

def _manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _passable(state, x, y):
    if not (0 <= x < state["width"] and 0 <= y < state["height"]):
        return False
    return state["tiles"][f"{x},{y}"]["terrain"] != "water"


def _step_toward(state, pos, target):
    """One greedy step; prefers the longer axis, sidesteps water."""
    x, y = pos
    dx = target[0] - x
    dy = target[1] - y
    candidates = []
    if abs(dx) >= abs(dy) and dx != 0:
        candidates.append((x + (1 if dx > 0 else -1), y))
    if dy != 0:
        candidates.append((x, y + (1 if dy > 0 else -1)))
    if dx != 0:
        step = (x + (1 if dx > 0 else -1), y)
        if step not in candidates:
            candidates.append(step)
    for nx, ny in [(x, y - 1), (x + 1, y), (x, y + 1), (x - 1, y)]:
        if (nx, ny) not in candidates:
            candidates.append((nx, ny))
    for nx, ny in candidates:
        if _passable(state, nx, ny):
            return [nx, ny]
    return None


def _path_toward(state, pos, target, max_steps):
    path = []
    cur = list(pos)
    for _ in range(max_steps):
        if cur == list(target):
            break
        nxt = _step_toward(state, cur, target)
        if nxt is None:
            break
        path.append(nxt)
        cur = nxt
    return path


def _nearest_deposit(state, pos, kind):
    best = None
    for key in sorted(state["tiles"]):
        tile = state["tiles"][key]
        d = tile["deposit"]
        if d is not None and d["kind"] == kind and d["qty"] > 0:
            x, y = (int(v) for v in key.split(","))
            score = (_manhattan(pos, (x, y)), x, y)
            if best is None or score < best[0]:
                best = (score, [x, y])
    return best[1] if best else None


def _deliver(state, agent_id, item, content):
    """Move toward the site; contribute in the same tick if we can arrive."""
    pos = state["agents"][agent_id]["pos"]
    site = state["project"]["site"]
    if pos == site:
        return [{"verb": "contribute", "item": item, "qty": 1}]
    path = _path_toward(state, pos, site, content["move_points"])
    bundle = [{"verb": "move", "path": path}] if path else []
    if path and path[-1] == site:
        bundle.append({"verb": "contribute", "item": item, "qty": 1})
    return bundle


def _campfire_exists(state):
    return any(
        t["building"] is not None and t["building"]["kind"] == "campfire"
        for t in state["tiles"].values()
    )


def _build_tile(state):
    """First empty passable tile adjacent to the site."""
    sx, sy = state["project"]["site"]
    for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
        x, y = sx + dx, sy + dy
        if _passable(state, x, y) and state["tiles"][f"{x},{y}"]["building"] is None:
            return [x, y]
    for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
        x, y = sx + dx, sy + dy
        if _passable(state, x, y):
            return [x, y]
    return [sx, sy + 1]


# --- greedy roles -----------------------------------------------------------

def _gatherer(state, agent_id, spec, content, roles):
    a = state["agents"][agent_id]
    inv = a["inventory"]
    project = state["project"]
    need_base = content["recipes"][spec["component"]]["inputs"][spec["base"]]
    gift_total = sum(spec["gift"].values())

    if inv.get(spec["component"], 0) >= 1:
        return _deliver(state, agent_id, spec["component"], content)

    if project["contributed"].get(spec["component"], 0) >= project["needs"].get(spec["component"], 0):
        # Delivered. Gift campfire materials to the meal bot if still useful.
        if roles is None or _campfire_exists(state):
            return []
        meal_agent = next((aid for aid, r in sorted(roles.items()) if r == "meal"), None)
        if meal_agent is None or meal_agent == agent_id:
            return []
        already_open = any(
            o["from"] == agent_id and o["to"] == meal_agent
            for o in state["offers"].values()
        )
        if already_open:
            return []
        if all(inv.get(i, 0) >= q for i, q in spec["gift"].items()):
            return [{"verb": "offer", "to": meal_agent,
                     "give": dict(spec["gift"]), "want": {}}]
        return []

    if inv.get(spec["base"], 0) >= need_base + gift_total:
        return [{"verb": "craft", "recipe": spec["component"]}]

    pos = a["pos"]
    tile = state["tiles"][f"{pos[0]},{pos[1]}"]
    needed = need_base + gift_total - inv.get(spec["base"], 0)
    if (
        tile["deposit"] is not None
        and tile["deposit"]["kind"] == spec["deposit"]
        and tile["deposit"]["qty"] > 0
    ):
        n = min(needed, tile["deposit"]["qty"], 8)
        return [{"verb": "harvest"} for _ in range(n)]

    target = _nearest_deposit(state, pos, spec["deposit"])
    if target is None:
        return []
    path = _path_toward(state, pos, target, content["move_points"])
    return [{"verb": "move", "path": path}] if path else []


def _meal(state, agent_id, content):
    a = state["agents"][agent_id]
    inv = a["inventory"]
    pos = a["pos"]
    project = state["project"]

    if inv.get("cooked_meal", 0) >= 1:
        return _deliver(state, agent_id, "cooked_meal", content)

    if project["contributed"].get("cooked_meal", 0) >= project["needs"].get("cooked_meal", 0):
        return []

    incoming = [oid for oid in sorted(state["offers"])
                if state["offers"][oid]["to"] == agent_id]
    if incoming:
        return [{"verb": "accept", "offer_id": oid} for oid in incoming[:8]]

    if inv.get("berries", 0) < 3:
        tile = state["tiles"][f"{pos[0]},{pos[1]}"]
        if (
            tile["deposit"] is not None
            and tile["deposit"]["kind"] == "berry_bush"
            and tile["deposit"]["qty"] > 0
        ):
            n = min(3 - inv.get("berries", 0), tile["deposit"]["qty"], 8)
            return [{"verb": "harvest"} for _ in range(n)]
        target = _nearest_deposit(state, pos, "berry_bush")
        if target is not None:
            path = _path_toward(state, pos, target, content["move_points"])
            return [{"verb": "move", "path": path}] if path else []

    build_tile = _build_tile(state)
    have_materials = inv.get("wood", 0) >= 2 and inv.get("stone", 0) >= 1
    here = state["tiles"][f"{pos[0]},{pos[1]}"]

    if here["building"] is not None and here["building"]["kind"] == "campfire":
        if inv.get("berries", 0) >= 3:
            return [{"verb": "craft", "recipe": "cooked_meal"}]

    if have_materials:
        if pos == build_tile and here["building"] is None:
            bundle = [{"verb": "build", "building": "campfire"}]
            if inv.get("berries", 0) >= 3:
                bundle.append({"verb": "craft", "recipe": "cooked_meal"})
            return bundle
        path = _path_toward(state, pos, build_tile, content["move_points"])
        return [{"verb": "move", "path": path}] if path else []

    if _campfire_exists(state) and inv.get("berries", 0) >= 3:
        for key in sorted(state["tiles"]):
            t = state["tiles"][key]
            if t["building"] is not None and t["building"]["kind"] == "campfire":
                x, y = (int(v) for v in key.split(","))
                path = _path_toward(state, pos, (x, y), content["move_points"])
                return [{"verb": "move", "path": path}] if path else []

    # Wait for gifts near the site; periodically say what is still needed so
    # non-scripted teammates can discover the cooperation.
    bundle = []
    if pos != build_tile:
        path = _path_toward(state, pos, build_tile, content["move_points"])
        if path:
            bundle.append({"verb": "move", "path": path})
    if state["tick"] % 3 == 0 and not have_materials:
        bundle.append({
            "verb": "say",
            "text": "I can cook the meal for the beacon. Please send me an offer "
                    "of 2 wood and 1 stone so I can build a campfire at the site.",
        })
    return bundle


# --- provisioner (full-content food specialist) -----------------------------

def _nearest_building(state, pos, kind):
    best = None
    for key in sorted(state["tiles"]):
        b = state["tiles"][key]["building"]
        if b is not None and b["kind"] == kind:
            x, y = (int(v) for v in key.split(","))
            score = (_manhattan(pos, (x, y)), x, y)
            if best is None or score < best[0]:
                best = (score, [x, y])
    return best[1] if best else None


def _gather(state, agent_id, kind, needed, content):
    """Harvest `needed` units of a deposit kind, or walk toward the nearest."""
    if needed <= 0:
        return []
    a = state["agents"][agent_id]
    pos = a["pos"]
    tile = state["tiles"][f"{pos[0]},{pos[1]}"]
    d = tile["deposit"]
    if d is not None and d["kind"] == kind and d["qty"] > 0:
        return [{"verb": "harvest"} for _ in range(min(needed, d["qty"], 6))]
    target = _nearest_deposit(state, pos, kind)
    if target is None:
        return []
    path = _path_toward(state, pos, target, content["move_points"])
    return [{"verb": "move", "path": path}] if path else []


def _provisioner(state, agent_id, content):
    a = state["agents"][agent_id]
    skills = a.get("skills", {})
    inv = a["inventory"]
    pos = a["pos"]

    if "foraging" not in skills:
        return [{"verb": "study", "profession": "foraging"}]
    if "cooking" not in skills:
        return [{"verb": "study", "profession": "cooking"}]

    bundle = []

    # Feed itself before anything else.
    if a["calories"] < 300:
        for food in ("cooked_meal", "berries", "greens"):
            if inv.get(food, 0) >= 1:
                bundle.append({"verb": "eat", "item": food})
                break

    # Gift a meal to the hungriest settler (one open gift at a time).
    if inv.get("cooked_meal", 0) >= 2:
        others = sorted(
            (oid for oid in state["agents"] if oid != agent_id),
            key=lambda oid: (state["agents"][oid]["calories"], oid),
        )
        already = any(
            o["from"] == agent_id and "cooked_meal" in o["give"]
            for o in state["offers"].values()
        )
        if others and not already:
            bundle.append({"verb": "offer", "to": others[0],
                           "give": {"cooked_meal": 1}, "want": {}})

    campfire = _nearest_building(state, pos, "campfire")

    if campfire is None:
        if inv.get("wood", 0) < 2:
            return bundle + _gather(state, agent_id, "trees",
                                    2 - inv.get("wood", 0), content)
        if inv.get("stone", 0) < 1:
            return bundle + _gather(state, agent_id, "stone_outcrop", 1, content)
        tile = state["tiles"][f"{pos[0]},{pos[1]}"]
        if tile["building"] is None and pos != state["project"]["site"]:
            bundle.append({"verb": "build", "building": "campfire"})
            return bundle
        step_away = _step_toward(state, pos, (pos[0] + 1, pos[1]))
        if step_away:
            bundle.append({"verb": "move", "path": [step_away]})
        return bundle

    if inv.get("berries", 0) >= 3:
        if pos == campfire:
            bundle.append({"verb": "craft", "recipe": "cooked_meal"})
        else:
            path = _path_toward(state, pos, campfire, content["move_points"])
            if path:
                bundle.append({"verb": "move", "path": path})
                if path[-1] == campfire:
                    bundle.append({"verb": "craft", "recipe": "cooked_meal"})
        return bundle

    if inv.get("cooked_meal", 0) < 4:
        bundle += _gather(state, agent_id, "berry_bush",
                          3 - inv.get("berries", 0), content)

    if state["tick"] % 5 == 0:
        bundle.append({
            "verb": "say",
            "text": f"Hot meals at the campfire ({campfire[0]},{campfire[1]}) - "
                    "I will trade cooked_meal for wood, stone, or berries.",
        })
    return bundle


# --- random fuzzer ----------------------------------------------------------

def _random_bot(state, agent_id, content):
    seed = state["seed"]
    tick = state["tick"]
    a = state["agents"][agent_id]
    x, y = a["pos"]
    choice = rand_below(seed, 4, "bot", tick, agent_id)
    if choice == 1 and state["tiles"][f"{x},{y}"]["deposit"] is not None:
        return [{"verb": "harvest"}]
    if choice == 2:
        return [{"verb": "say", "text": f"wandering at {x},{y}"}]
    if choice == 3:
        return [{"verb": "remember", "text": f"tick {tick} at {x},{y}"}]
    neighbors = [(nx, ny) for nx, ny in [(x, y - 1), (x + 1, y), (x, y + 1), (x - 1, y)]
                 if _passable(state, nx, ny)]
    if not neighbors:
        return []
    nx, ny = neighbors[rand_below(seed, len(neighbors), "bot_dir", tick, agent_id)]
    return [{"verb": "move", "path": [[nx, ny]]}]
