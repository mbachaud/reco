# Action Semantics (single source of truth)

Bundle: one JSON array, max 8 actions/tick. The bundle is not atomic; each
action is. Within a phase, agents execute in rotation order
`(stable_index + tick) mod N` where `stable_index` is a seed-shuffled
permutation fixed at tick 0. Within one agent's bundle: listed order. A failed
action is skipped; later actions still attempt against the then-current state.
Runner parse errors are `PE_*` (PE_EMPTY, PE_MALFORMED, PE_SCHEMA, PE_TIMEOUT,
PE_DRIVER); engine rejections are `R_*` events. Both are echoed to the agent in
its next observation.

| Verb (args) | Phase | Calories | Reserves / consumes | Visibility | Main rejection codes |
|---|---|---|---|---|---|
| `remember(text)` | 0 admin | 0 | — | private | R_TOO_LONG |
| `lookup(topic)` | 0 admin | 0 | — | private | R_UNKNOWN_TOPIC, R_LOOKUP_CAP |
| `say(text)` | 1 chat | 0 | — | global | R_CHAT_CAP, R_TOO_LONG |
| `dm(agent,text)` | 1 chat | 0 | — | recipient only | R_UNKNOWN_AGENT, R_CHAT_CAP |
| `claim(x,y)`* | 2 claims | 0 | consumes claim token | public event | R_NO_TOKEN, R_ALREADY_CLAIMED, R_UNCLAIMABLE |
| `grant/revoke(agent,x,y)`* | 2 claims | 0 | — | owner+grantee | R_NOT_OWNER |
| `create_currency(name)`* | 3 economy | 0 | — | public | R_NAME_TAKEN, R_CURRENCY_LIMIT |
| `mint(cur,amt)`* | 3 economy | 0 | — | supply public | R_NOT_ISSUER |
| `offer(to,give,want)` | 3 economy | 0 | escrows offered goods | counterparty | R_INSUFFICIENT_GOODS, R_OFFER_CAP, R_UNKNOWN_AGENT |
| `accept(offer_id)` | 3 economy | 0 | atomic escrow swap | parties + public trade event | R_OFFER_EXPIRED, R_INSUFFICIENT_FUNDS |
| `set_prices` / `stock/withdraw`* | 3 economy | 0 | stock moves to shop | public / owner | R_NO_SHOP, R_NOT_CO_LOCATED |
| `buy(shop,item,qty)`* | 3 economy | 0 | atomic pay+receive | public trade event | R_OUT_OF_STOCK, R_INSUFFICIENT_FUNDS, R_NOT_CO_LOCATED |
| `move(path)` | 4 movement | per tile | — | position public locally | R_IMPASSABLE, R_MOVE_BUDGET, R_STARVING |
| `harvest()` | 5 gather | yes | contested last units -> rotation order | local | R_DEPLETED, R_STARVING (non-food deposit at 0 cal), R_NO_PERMISSION*, R_TOOL_REQUIRED* |
| `eat(item)` | 6 production | gain | consumes item | private | R_NOT_FOOD, R_NOT_HELD |
| `study(profession)`* | 6 production | yes | consumes mastery slot | milestone public | R_MASTERY_CAP |
| `craft(recipe)` | 6 production | yes | consumes inputs; slice: 1-tick atomic | local | R_MISSING_INPUTS, R_NO_STATION, R_UNKNOWN_RECIPE, R_SKILL_TOO_LOW* |
| `build(building)` | 6 production | yes | consumes materials | public event | R_TILE_OCCUPIED, R_MISSING_MATERIALS, R_UNKNOWN_BUILDING |
| `contribute(item,qty)` | 6 production | 0 | consumes items | public milestone | R_WRONG_SITE, R_NOT_NEEDED, R_NOT_HELD |
| *(autonomous)* world step | 7 world | — | — | per event | — |

`*` = full-content phase (not in the vertical slice yet).

Phase 7 (autonomous, deterministic, no agent input): craft-job progression
(multi-tick recipes, full content), offer expiry with escrow return, claim
upkeep*, calorie decay + starving transition events, project/meteor
evaluation, milestone emission, tick increment.

Additional engine caps: R_ACTION_CAP (bundle > 8), R_UNKNOWN_VERB,
R_STARVING (at 0 calories only move(1)/eat/accept/harvest-of-food/chat/admin
run — accept stays open so a starving agent can take a food gift out of
escrow, and food deposits stay harvestable so a settlement cannot deadlock
with everyone at 0 calories while berries sit in the ground).
