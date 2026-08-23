"""Gather all cross-run analysis data into one JSON blob for the artifact."""
import json
import re
import collections

ROSTERS = {
    "campaign1": {
        "a1": ("Lark", "claude"), "a2": ("Aspen", "sol"), "a3": ("Juniper", "scripted"),
        "a4": ("Briar", "claude"), "a5": ("Brook", "sol"), "a6": ("Umber", "claude"),
        "a7": ("Quill", "sol"), "a8": ("Sorrel", "claude"), "a9": ("Kestrel", "sol"),
    },
    "campaign2": {
        "a1": ("Lark", "claude"), "a2": ("Juniper", "sol"), "a3": ("Briar", "scripted"),
        "a4": ("Brook", "sol"), "a5": ("Umber", "claude"), "a6": ("Quill", "scripted"),
        "a7": ("Sorrel", "claude"), "a8": ("Kestrel", "sol"), "a9": ("Onyx", "claude"),
        "a10": ("Aspen", "sol"),
    },
}
FOOD = {"berries", "greens", "vegetables", "bread", "cooked_meal", "hearty_stew"}


def load(run):
    ev, metrics, tick = [], [], -1
    with open(f"runs/{run}/log.jsonl", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("t") == "events":
                tick += 1
                for e in rec["events"]:
                    ev.append((tick, e))
            elif rec.get("t") == "metrics":
                metrics.append(rec)
    return ev, metrics


def follow_through(run, ev):
    roster = ROSTERS[run]
    names = {aid: n for aid, (n, p) in roster.items()}
    chats = [(t, e) for t, e in ev if e["type"] == "chat"]
    offers = [(t, e) for t, e in ev if e["type"] == "offer_created"]
    accepts = [(t, e) for t, e in ev if e["type"] == "offer_accepted"]
    builds = [(t, e) for t, e in ev if e["type"] == "built"]
    offer_meta = {e["offer_id"]: (t, e) for t, e in offers}

    def chat_between(a, b, lo, hi):
        for t, c in chats:
            if lo <= t <= hi and c["channel"] == "dm" and {c["from"], c.get("to")} == {a, b}:
                return "dm"
        for t, c in chats:
            if lo <= t <= hi and c["channel"] == "global" and c["from"] in (a, b):
                other = b if c["from"] == a else a
                if names[other].lower() in c["text"].lower():
                    return "named"
        return None

    off = collections.Counter(chat_between(o["from"], o["to"], t - 3, t) or "cold"
                              for t, o in offers)
    acc = collections.Counter()
    for t, a in accepts:
        o = offer_meta.get(a["offer_id"])
        if o:
            acc[chat_between(o[1]["from"], o[1]["to"], o[0] - 3, t) or "cold"] += 1

    first_kind, dups = {}, 0
    announced = 0
    for t, b in builds:
        kind = b["building"]
        if any(t - 5 <= ct <= t and kind.replace("_", " ") in c["text"].lower().replace("_", " ")
               for ct, c in chats):
            announced += 1
        if kind in first_kind:
            dups += 1
        else:
            first_kind[kind] = t

    need_re = re.compile(r"need[s]?\s+(?:some\s+|more\s+|\d+\s+)*([a-z_]+)")
    reqs = answered = 0
    for t, c in chats:
        m = need_re.search(c["text"].lower())
        if not m:
            continue
        reqs += 1
        if any(t < ot <= t + 5 and o["to"] == c["from"] and m.group(1) in o["give"]
               for ot, o in offers):
            answered += 1

    return {
        "offers": {"total": len(offers), **dict(off)},
        "accepted": {"total": len(accepts), **dict(acc)},
        "builds": {"total": len(builds), "announced": announced, "duplicates": dups},
        "requests": {"total": reqs, "answered": answered},
    }


def matrices(run, ev):
    prov = {aid: p for aid, (n, p) in ROSTERS[run].items()}
    offers = {e["offer_id"]: e for t, e in ev if e["type"] == "offer_created"}
    dm = collections.Counter()
    trade = collections.Counter()
    gift = collections.Counter()
    for t, e in ev:
        if e["type"] == "chat" and e["channel"] == "dm" and e.get("to"):
            dm[f"{prov[e['from']]}\u2192{prov[e['to']]}"] += 1
        elif e["type"] == "offer_accepted":
            o = offers.get(e["offer_id"])
            if o:
                key = f"{prov[o['from']]}\u2192{prov[o['to']]}"
                trade[key] += 1
                if not o["want"] and not o.get("want_credits"):
                    gift[key] += 1
    return {"dm": dict(dm), "trade": dict(trade), "gift": dict(gift)}


def rejections(run, ev):
    prov = {aid: p for aid, (n, p) in ROSTERS[run].items()}
    rej = collections.defaultdict(collections.Counter)
    for t, e in ev:
        if e["type"] == "rejected" and e.get("agent") in prov:
            rej[prov[e["agent"]]][e["code"]] += 1
    return {p: dict(c.most_common(6)) for p, c in rej.items()}


def usage(run):
    prov = {aid: p for aid, (n, p) in ROSTERS[run].items()}
    agg = collections.defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "cache_read": 0})
    with open(f"runs/{run}/journal.jsonl", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            out = rec.get("outcome", {})
            u = out.get("usage") or {}
            if not u:
                continue
            p = prov.get(rec["agent"])
            a = agg[p]
            a["calls"] += 1
            a["in"] += u.get("input_tokens", 0)
            a["out"] += u.get("output_tokens", 0)
            a["cache_read"] += u.get("cache_read_input_tokens", 0)
    return dict(agg)


def calorie_series(run):
    import sys
    sys.path.insert(0, ".")
    from reco.runner.frames import export_frames
    data = export_frames(f"runs/{run}")
    names = {aid: n for aid, (n, p) in ROSTERS[run].items()}
    prov = {aid: p for aid, (n, p) in ROSTERS[run].items()}
    series = collections.defaultdict(list)
    frames = data["frames"] if isinstance(data, dict) else data
    for fr in frames:
        for aid, a in fr["agents"].items():
            series[aid].append(a["calories"] if isinstance(a, dict) else a[2])
    step = 2
    return {names[aid]: {"provider": prov[aid], "series": s[::step]}
            for aid, s in series.items()}, step


def currency_story(ev, roster):
    names = {aid: n for aid, (n, p) in roster.items()}
    out = []
    for t, e in ev:
        if e["type"] in ("currency_created", "minted", "stocked", "prices_set",
                         "claimed", "claim_lapsed"):
            who = names.get(e.get("agent") or e.get("from"), "?")
            out.append({"tick": t, "who": who, "event": e["type"],
                        "detail": {k: v for k, v in e.items()
                                   if k not in ("type", "agent", "from")}})
    return out


result = {}
for run in ("campaign1", "campaign2"):
    ev, metrics = load(run)
    cal, cal_step = calorie_series(run)
    result[run] = {
        "follow": follow_through(run, ev),
        "matrices": matrices(run, ev),
        "rejections": rejections(run, ev),
        "usage": usage(run),
        "metrics": {
            "tick": [m["tick"] for m in metrics][::2],
            "calories_mean": [m["calories_mean"] for m in metrics][::2],
            "gini": [m["wealth_gini_milli"] for m in metrics][::2],
            "entropy": [m["specialization_entropy_milli"] for m in metrics][::2],
            "trades": [m["trade_count"] for m in metrics],
            "production": [m["production_value"] for m in metrics],
        },
        "calories": cal,
        "cal_step": cal_step,
    }
result["campaign1"]["currency_story"] = currency_story(load("campaign1")[0],
                                                       ROSTERS["campaign1"])
out_path = "runs/analysis_data.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(result, f)
print("wrote", out_path)
for run in result:
    if run.startswith("campaign"):
        print(run, "usage:", result[run]["usage"])
print("currency story:", json.dumps(result["campaign1"]["currency_story"])[:600])
