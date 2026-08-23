# The Scripted Worker

Reco ships a family of scripted bot policies
([`reco/gateway/drivers/scripted.py`](../reco/gateway/drivers/scripted.py))
that play through exactly the same action interface as the LLM drivers. They
are deterministic pure functions of the full world state — no quota, no
latency, no parsing errors — which makes them useful three ways:

1. **Engine development and fuzzing** (`random` role) — a seeded walker that
   moves, harvests, chats, and writes memories using the engine's own
   keyed-hash RNG, so fuzz runs replay bit-for-bit.
2. **End-to-end verification** (`wood` / `stone` / `meal` roles) — a minimal
   crew that can actually *win* the vertical-slice objective: gatherers
   harvest their deposit, deliver their component to the project site, then
   gift surplus materials to the meal bot, which builds a campfire beside the
   site, cooks, and delivers.
3. **Benchmark support and baseline** (`provisioner` role) — the "camp cook"
   seated alongside LLM agents in both public campaigns.

Because scripted bots read the full state rather than the rendered
observation, they are a *support role and baseline*, not a fair benchmark
entrant — they exist to isolate what the LLM agents are being measured on.

## The provisioner policy

The provisioner solves exactly one problem: keep the colony fed. Its policy,
in priority order each tick:

1. **Skill up**: study `foraging`, then `cooking` (one study per tick until
   both are held).
2. **Feed itself** below 300 calories, eating the best food on hand
   (`cooked_meal` → `berries` → `greens`).
3. **Gift a meal** whenever it holds ≥ 2 cooked meals: it posts a free offer
   (`give: 1 cooked_meal, want: nothing`) to the *hungriest* other settler,
   keeping at most one such gift open at a time so escrow never silts up.
4. **Establish a kitchen**: if no campfire exists anywhere, gather 2 wood and
   1 stone and build one on the first legal tile (never on the project site).
5. **Cook**: with ≥ 3 berries in hand, walk to the nearest campfire and craft
   `cooked_meal` — movement and crafting composed into a single tick's bundle
   when the path arrives in range.
6. **Restock**: below 4 meals banked, gather from the nearest berry bush.
7. **Advertise**: every 5th tick, broadcast the campfire location and a
   standing offer to trade meals for wood, stone, or berries.

All targeting is deterministic: nearest-deposit selection sorts tiles in a
stable order, pathing is a greedy step-toward with water sidesteps, and the
hungriest-settler sort breaks ties by agent id. Two provisioners on the same
map interleave without coordination because each re-reads the live state
every tick.

## What the campaigns showed

- **Campaign 1** seated one provisioner among eight LLM agents. It ran at
  100% compliance and zero rejections, but one cook could not outrun the
  colony's calorie burn — five of nine agents starved before the meteor.
- **Campaign 2** seated two provisioners (spawned near berry-rich plains)
  on the fixed engine. Nobody starved; both cooks leveled cooking to 3.
- The policy's ceiling is also visible in the data: it only knows the
  `cooked_meal` recipe, so even at cooking level 3 it never produced the
  `rations_crate` the Defense Array needed. A scripted role is exactly as
  good as its script — the open coordination problems belong to the LLM
  agents.

## Determinism contract

Scripted decisions use only: the committed state dict, the agent id, the
content pack, and the engine RNG (`rand_below(seed, n, label, tick, agent)`).
No wall clock, no floats, no Python `random`. A replayed run reproduces every
scripted decision exactly, which is what lets `reco replay` verify the full
chained state hash of a mixed LLM + scripted campaign.
