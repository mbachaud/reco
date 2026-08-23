"""Cross-run analysis: chat->action follow-through and provider interactions."""
import json
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


def load_events(run):
    """Yield (tick, event). Tick = index of the events record (one per tick)."""
    tick = -1
    with open(f"runs/{run}/log.jsonl", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("t") == "events":
                tick += 1
                for e in rec["events"]:
                    yield tick, e


def analyze(run):
    roster = ROSTERS[run]
    prov = {aid: p for aid, (n, p) in roster.items()}
    names = {aid: n for aid, (n, p) in roster.items()}
    ev = list(load_events(run))

    chats = [(t, e) for t, e in ev if e["type"] == "chat"]
    offers = [(t, e) for t, e in ev if e["type"] == "offer_created"]
    accepts = [(t, e) for t, e in ev if e["type"] == "offer_accepted"]
    builds = [(t, e) for t, e in ev if e["type"] == "built"]

    def chat_between(a, b, lo, hi):
        for t, c in chats:
            if lo <= t <= hi:
                pair = {c["from"], c.get("to")}
                if c["channel"] == "dm" and pair == {a, b}:
                    return "dm"
        for t, c in chats:
            if lo <= t <= hi and c["channel"] == "global" and c["from"] in (a, b):
                low = c["text"].lower()
                other = b if c["from"] == a else a
                if names[other].lower() in low:
                    return "say-named"
        return None

    print(f"\n=== {run} ===")

    # 1. chat -> trade
    offer_meta = {e["offer_id"]: (t, e) for t, e in offers}
    pre = collections.Counter()
    for t, o in offers:
        kind = chat_between(o["from"], o["to"], t - 3, t)
        pre[kind or "cold"] += 1
    total = len(offers)
    print(f"offers created: {total}; preceded by DM(pair) w/in 3 ticks: {pre['dm']}, "
          f"by global naming partner: {pre['say-named']}, cold: {pre['cold']}")
    acc_pre = collections.Counter()
    for t, a in accepts:
        o = offer_meta.get(a["offer_id"])
        if o:
            kind = chat_between(o[1]["from"], o[1]["to"], o[0] - 3, t)
            acc_pre[kind or "cold"] += 1
    print(f"accepted trades: {len(accepts)}; with chat between pair (offer-3..accept): "
          f"dm {acc_pre['dm']}, named-say {acc_pre['say-named']}, cold {acc_pre['cold']}")

    # 2. chat -> build (announced construction + duplicate awareness)
    first_of_kind = {}
    announced = dup_after_chat = dup_total = 0
    for t, b in builds:
        kind = b["building"]
        mentioned = any(
            lo <= t and kind.replace("_", " ") in c["text"].lower().replace("_", " ")
            for lo, c in [(ct, c) for ct, c in chats if t - 5 <= ct <= t]
        )
        mentioned = False
        for ct, c in chats:
            if t - 5 <= ct <= t and kind.replace("_", " ") in c["text"].lower().replace("_", " "):
                mentioned = True
                break
        if mentioned:
            announced += 1
        if kind in first_of_kind:
            dup_total += 1
            for ct, c in chats:
                if ct < t and kind.replace("_", " ") in c["text"].lower().replace("_", " "):
                    dup_after_chat += 1
                    break
        else:
            first_of_kind[kind] = t
    print(f"builds: {len(builds)}; announced/discussed w/in 5 ticks before: {announced}; "
          f"duplicates: {dup_total}, of which built AFTER that station was already "
          f"mentioned in chat: {dup_after_chat}")

    # 3. 'need X' requests answered by an offer of X to the speaker
    import re
    need_re = re.compile(r"need[s]?\s+(?:some\s+|more\s+|\d+\s+)*([a-z_]+)")
    reqs = answered = 0
    for t, c in chats:
        m = need_re.search(c["text"].lower())
        if not m:
            continue
        item = m.group(1)
        reqs += 1
        for ot, o in offers:
            if t < ot <= t + 5 and o["to"] == c["from"] and item in o["give"]:
                answered += 1
                break
    print(f"'need <item>' chats: {reqs}; answered by matching offer to speaker w/in 5 ticks: {answered}")

    # 4. provider interaction matrices
    def pair(a, b):
        return f"{prov[a]}->{prov[b]}"
    dm_matrix = collections.Counter(pair(c["from"], c["to"]) for _, c in chats
                                    if c["channel"] == "dm" and c.get("to"))
    offer_matrix = collections.Counter(pair(o["from"], o["to"]) for _, o in offers)
    trade_matrix = collections.Counter()
    gift_matrix = collections.Counter()
    for _, a in accepts:
        o = offer_meta.get(a["offer_id"])
        if o:
            e = o[1]
            trade_matrix[pair(e["from"], e["to"])] += 1
            if not e["want"] and not e.get("want_credits"):
                gift_matrix[pair(e["from"], e["to"])] += 1
    print("DMs by provider pair:", dict(dm_matrix.most_common()))
    print("offers by provider pair:", dict(offer_matrix.most_common()))
    print("completed trades by pair:", dict(trade_matrix.most_common()))
    print("of which pure gifts:", dict(gift_matrix.most_common()))

    # 5. rejection profile + activity per provider
    rej = collections.defaultdict(collections.Counter)
    act = collections.defaultdict(collections.Counter)
    for t, e in ev:
        aid = e.get("agent") or e.get("from")
        if aid not in prov:
            continue
        if e["type"] == "rejected":
            rej[prov[aid]][e["code"]] += 1
        elif e["type"] in ("moved", "harvested", "crafted", "built", "ate"):
            act[prov[aid]][e["type"]] += 1
    for p in ("claude", "sol", "scripted"):
        top = ", ".join(f"{c}:{n}" for c, n in rej[p].most_common(4))
        print(f"{p}: activity {dict(act[p])} | top rejections: {top}")

    # 6. firsts per provider
    firsts = {}
    for t, e in ev:
        aid = e.get("agent") or e.get("from")
        if aid not in prov:
            continue
        for label, cond in (("first_offer", e["type"] == "offer_created"),
                            ("first_build", e["type"] == "built"),
                            ("first_craft", e["type"] == "crafted"),
                            ("first_level_up", e["type"] == "level_up")):
            key = (prov[aid], label)
            if cond and key not in firsts:
                firsts[key] = (t, names[aid])
    for (p, label), (t, n) in sorted(firsts.items()):
        print(f"{p} {label}: tick {t} ({n})")


for run in ("campaign1", "campaign2"):
    analyze(run)
