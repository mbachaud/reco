# Reco — Synthetic Civilization Benchmark

A text-only, Eco-inspired multi-agent world for benchmarking LLM agents as a
*civilization*: gathering, crafting, food, trade, chat, and a cooperative
mega-project no agent can finish alone. Same seed, different provider rosters,
deterministic replay of every run.

- **Engine**: pure and deterministic — `(state, candidate actions, seed) →
  (state', events)`. Integer-only, keyed-hash randomness, rotating priority.
  The engine owns all semantic validation (`R_*` rejection events).
- **Runner**: collects and parses only (`PE_*` errors), journals every
  decision durably *before* resolution, commits chained tick records, resumes
  across crashes and rate-limit pauses.
- **Drivers**: Track A subscription CLIs (`claude -p`, `codex exec`,
  hardened + leakage-tested) and Track B OpenAI-compatible HTTP (APIs, Ollama,
  LM Studio) — the repeatable benchmark track. Plus deterministic scripted
  baselines (see below).
- **Anonymity**: agents see display names only; the manifest maps names to
  providers for human reviewers.

## Results so far

Two full campaigns on the shipped engine, both seed 2718, full content
(~40 items, 4 tiers), 24×24 map, meteor at tick 170. The colony loses unless
agents jointly deliver the Defense Array components before impact.

| | Campaign 1 | Campaign 2 |
|---|---|---|
| Roster | 4× Claude Haiku 4.5 · 4× GPT-5.6 (codex) · 1 scripted provisioner | 4× Claude Sonnet 5 · 4× GPT-5.6 (codex) · 2 scripted provisioners |
| Outcome | **Meteor impact** — 0 components delivered | **Meteor impact** — 0 components delivered |
| Survival | 5 of 9 agents starved before impact | **All 10 alive at impact** |
| Production value | 558 | 1257 |
| Trades | 50 (volume 205) | 196 (volume 1007) |
| Chat messages | 2662 | 2721 |
| Action compliance | ≥ 99.4% per agent | ≥ 98.8% per agent |

**Campaign 1** ([report](runs/campaign1/report.md)): the colony starved.
Agents talked constantly (2662 messages) but food production collapsed; one
scripted cook could not feed eight LLM agents, and starving agents were
locked out of the verbs that would have saved them.

**Campaign 2** ([report](runs/campaign2/report.md)): the rematch on the fixed
engine (starving agents can accept gifts and forage), with Sonnet 5 replacing
Haiku and a second cook. Survival was solved outright and the economy grew
2–4×, but the Defense Array still got zero contributions. The wall moved from
food to progression: every meteor component sits behind a level-3 profession
(~20 crafts of XP), and the required workshop/factory materials themselves
need professions nobody could level without those stations. A coordination
pathology made it vivid: the colony answered `R_NO_STATION` rejections by
building **eight mason benches** instead of routing work to one specialist.

Each run directory carries the full evidence: `report.md` / `report.json`
(per-agent stats), `summary.json` (final state hash), `journal.jsonl` (every
raw model response), `log.jsonl` (the chained event log), and `viewer.html`
(a self-contained replay viewer — open it in a browser). Verify a run
yourself, no provider access needed:

```bash
python -m reco.cli replay runs/campaign2   # recomputes the chained state hashes
```

Campaign 2 replays hash-perfect on this code. Campaign 1 was run on the
pre-fix engine (before starving agents could accept gifts or forage), so its
log replays only against that engine revision — its report, journal, and
viewer are published here as the historical record.

## Quickstart

```bash
python -m venv .venv && .venv/Scripts/pip install -e .[dev]
pytest                                        # full suite, no providers needed
python -m reco.cli run --config reco/configs/smoke.yaml --out runs/smoke
python -m reco.cli replay runs/smoke          # provider-free integrity check
python -m reco.cli report runs/smoke          # report.md + report.json
python -m reco.cli conformance --driver cli_claude --model claude-haiku-4-5-20251001 --out runs/conf.json
```

## Docs

- `docs/action-semantics.md` — the verb/phase/rejection contract
- `docs/log-and-hashing.md` — canonical hashing, journal, chained commits, replay
- `docs/scripted-provisioner.md` — the deterministic scripted worker used as a
  baseline and support role in both campaigns
