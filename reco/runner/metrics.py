"""Per-tick civilization metrics.

Everything is valued in a real-goods numeraire derived deterministically from
content (raw item = 1 labor unit, crafted = inputs + 1) so currency printing
and wash trading cannot inflate GDP or trade volume. Integer-only so metrics
records stay canonical.
"""


def value_table(content: dict) -> dict[str, int]:
    values = {item: 1 for item in content["items"]}
    # Recipes may chain; iterate to a fixed point (tiny content, cheap).
    for _ in range(len(content["recipes"]) + 1):
        for name, recipe in sorted(content["recipes"].items()):
            cost = sum(values[i] * q for i, q in recipe["inputs"].items())
            values[name] = max(1, (cost + 1) // recipe["output_qty"])
    return values


def gini_milli(wealths: list[int]) -> int:
    """Gini coefficient x1000, integer math."""
    n = len(wealths)
    total = sum(wealths)
    if n == 0 or total == 0:
        return 0
    sorted_w = sorted(wealths)
    weighted = sum((i + 1) * w for i, w in enumerate(sorted_w))
    # G = (2*sum(i*w_i) / (n*total)) - (n+1)/n, scaled to milli-units.
    return round(2000 * weighted / (n * total) - 1000 * (n + 1) / n)


def specialization_entropy_milli(skills_by_agent: dict) -> int:
    """Mean normalized entropy of each agent's XP distribution over
    professions, x1000. Low = specialized workforce, high = generalists.
    Integer output; internal math may use floats (reporting only)."""
    import math

    entropies = []
    for skills in skills_by_agent.values():
        xps = [max(1, sk["xp"]) for sk in skills.values()]
        if len(xps) < 2:
            entropies.append(0.0)
            continue
        total = sum(xps)
        h = -sum((x / total) * math.log(x / total) for x in xps)
        entropies.append(h / math.log(len(xps)))
    if not entropies:
        return 0
    return round(1000 * sum(entropies) / len(entropies))


def compute_metrics(state: dict, events: list[dict], content: dict,
                    closed_offers: dict | None = None) -> dict:
    """closed_offers: offers consumed this tick (accepted), keyed by id —
    needed because accepted offers are gone from state by resolution end."""
    values = value_table(content)
    production = 0
    trade_count = trade_volume = chat_count = rejection_count = contributions = 0
    for e in events:
        kind = e["type"]
        if kind == "harvested":
            production += values.get(e["item"], 1) * e["qty"]
        elif kind == "crafted":
            recipe = content["recipes"][e["recipe"]]
            production += values.get(e["recipe"], 1) * recipe["output_qty"]
        elif kind == "offer_accepted":
            trade_count += 1
            offer = (closed_offers or {}).get(e["offer_id"])
            if offer:
                moved = list(offer["give"].items()) + list(offer["want"].items())
                trade_volume += sum(values.get(i, 1) * q for i, q in moved)
        elif kind == "chat":
            chat_count += 1
        elif kind == "rejected":
            rejection_count += 1
        elif kind == "contributed":
            contributions += e["qty"]

    agents = state["agents"]
    wealths = [
        sum(values.get(i, 1) * q for i, q in a["inventory"].items())
        for _, a in sorted(agents.items())
    ]
    calories = [a["calories"] for _, a in sorted(agents.items())]
    project = state["project"]
    return {
        "production_value": production,
        "trade_count": trade_count,
        "trade_volume": trade_volume,
        "chat_count": chat_count,
        "rejection_count": rejection_count,
        "contributions": contributions,
        "calories_mean": sum(calories) // max(1, len(calories)),
        "wealth_gini_milli": gini_milli(wealths),
        "specialization_entropy_milli": specialization_entropy_milli(
            {aid: a["skills"] for aid, a in sorted(agents.items()) if a.get("skills")}
        ),
        "project_progress": sum(project["contributed"].values()),
        "project_needed": sum(project["needs"].values()),
    }
