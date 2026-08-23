"""Full-content economy: player currencies, shops, land claims with upkeep."""
import copy

import pytest

from reco.engine.mapgen import init_state
from reco.engine.step import step
from tests.conftest import of_type, rejections
from tests.test_step_core import put


@pytest.fixture
def econtent(content):
    c = copy.deepcopy(content)
    c["currencies"] = {"max_per_agent": 1}
    c["claims"] = {"tokens_per_agent": 2, "upkeep_every": 4, "upkeep_cost": {"wood": 1}}
    c["buildings"]["shop"] = {"materials": {"wood": 2}}
    return c


@pytest.fixture
def estate(econtent):
    return init_state(seed=42, content=econtent, agent_ids=["a1", "a2", "a3"])


class TestCurrencies:
    def test_create_and_mint(self, estate, econtent):
        bundle = [{"verb": "create_currency", "name": "shells"},
                  {"verb": "mint", "currency": "shells", "amount": 100}]
        new, events = step(estate, {"a1": bundle}, econtent)
        assert new["currencies"]["shells"] == {"issuer": "a1", "supply": 100}
        assert new["agents"]["a1"]["balances"] == {"shells": 100}
        assert of_type(events, "currency_created")

    def test_name_taken(self, estate, econtent):
        s, _ = step(estate, {"a1": [{"verb": "create_currency", "name": "shells"}]}, econtent)
        _, events = step(s, {"a2": [{"verb": "create_currency", "name": "shells"}]}, econtent)
        assert rejections(events, "a2", "R_NAME_TAKEN")

    def test_currency_limit(self, estate, econtent):
        bundle = [{"verb": "create_currency", "name": "shells"},
                  {"verb": "create_currency", "name": "beads"}]
        _, events = step(estate, {"a1": bundle}, econtent)
        assert rejections(events, "a1", "R_CURRENCY_LIMIT")

    def test_only_issuer_mints(self, estate, econtent):
        s, _ = step(estate, {"a1": [{"verb": "create_currency", "name": "shells"}]}, econtent)
        _, events = step(s, {"a2": [{"verb": "mint", "currency": "shells", "amount": 5}]}, econtent)
        assert rejections(events, "a2", "R_NOT_ISSUER")

    def test_offer_with_credits(self, estate, econtent):
        estate["currencies"]["shells"] = {"issuer": "a1", "supply": 50}
        estate["agents"]["a1"]["balances"] = {"shells": 50}
        put(estate, "a2", inv={"stone": 3})
        s, _ = step(estate, {"a1": [{"verb": "offer", "to": "a2", "give": {},
                                     "give_credits": {"shells": 20},
                                     "want": {"stone": 3}}]}, econtent)
        assert s["agents"]["a1"]["balances"] == {"shells": 30}  # escrowed
        offer_id = next(iter(s["offers"]))
        s2, events = step(s, {"a2": [{"verb": "accept", "offer_id": offer_id}]}, econtent)
        assert s2["agents"]["a2"]["balances"] == {"shells": 20}
        assert s2["agents"]["a1"]["inventory"] == {"stone": 3}
        assert of_type(events, "offer_accepted")

    def test_expired_credit_offer_returns_escrow(self, estate, econtent):
        estate["currencies"]["shells"] = {"issuer": "a1", "supply": 50}
        estate["agents"]["a1"]["balances"] = {"shells": 50}
        s, _ = step(estate, {"a1": [{"verb": "offer", "to": "a2", "give": {},
                                     "give_credits": {"shells": 20}, "want": {"stone": 1}}]},
                    econtent)
        for _ in range(econtent["offers"]["ttl_ticks"] + 1):
            s, _ = step(s, {}, econtent)
        assert s["agents"]["a1"]["balances"] == {"shells": 50}


class TestShops:
    def make_shop(self, estate, econtent):
        # build is production phase; stock/set_prices are economy phase, which
        # runs earlier — so managing a new shop starts the NEXT tick.
        estate["tiles"]["3,3"]["building"] = None
        put(estate, "a1", pos=(3, 3), inv={"wood": 2, "cooked_meal": 4})
        estate["currencies"]["shells"] = {"issuer": "a1", "supply": 0}
        s, _ = step(estate, {"a1": [{"verb": "build", "building": "shop"}]}, econtent)
        bundle = [
            {"verb": "stock", "item": "cooked_meal", "qty": 4},
            {"verb": "set_prices", "item": "cooked_meal", "currency": "shells", "sell": 5},
        ]
        return step(s, {"a1": bundle}, econtent)

    def test_build_stock_price(self, estate, econtent):
        new, _ = self.make_shop(estate, econtent)
        shop = new["tiles"]["3,3"]["building"]
        assert shop["kind"] == "shop" and shop["owner"] == "a1"
        assert shop["stock"] == {"cooked_meal": 4}
        assert shop["prices"] == {"cooked_meal": {"currency": "shells", "sell": 5}}

    def test_buy_pays_owner_and_transfers(self, estate, econtent):
        s, _ = self.make_shop(estate, econtent)
        s["agents"]["a2"]["balances"] = {"shells": 12}
        put(s, "a2", pos=(3, 3))
        new, events = step(s, {"a2": [{"verb": "buy", "item": "cooked_meal", "qty": 2}]}, econtent)
        assert new["agents"]["a2"]["inventory"] == {"cooked_meal": 2}
        assert new["agents"]["a2"]["balances"] == {"shells": 2}
        assert new["agents"]["a1"]["balances"] == {"shells": 10}
        assert new["tiles"]["3,3"]["building"]["stock"] == {"cooked_meal": 2}
        assert of_type(events, "shop_sale")

    def test_buy_requires_colocation_funds_stock(self, estate, econtent):
        s, _ = self.make_shop(estate, econtent)
        put(s, "a2", pos=(5, 5))
        _, events = step(s, {"a2": [{"verb": "buy", "item": "cooked_meal", "qty": 1}]}, econtent)
        assert rejections(events, "a2", "R_NOT_CO_LOCATED")
        s["agents"]["a2"]["balances"] = {}
        put(s, "a2", pos=(3, 3))
        _, events = step(s, {"a2": [{"verb": "buy", "item": "cooked_meal", "qty": 1}]}, econtent)
        assert rejections(events, "a2", "R_INSUFFICIENT_FUNDS")
        _, events = step(s, {"a2": [{"verb": "buy", "item": "wood", "qty": 1}]}, econtent)
        assert rejections(events, "a2", "R_OUT_OF_STOCK")

    def test_only_owner_stocks(self, estate, econtent):
        s, _ = self.make_shop(estate, econtent)
        put(s, "a2", pos=(3, 3), inv={"wood": 1})
        _, events = step(s, {"a2": [{"verb": "stock", "item": "wood", "qty": 1}]}, econtent)
        assert rejections(events, "a2", "R_NOT_OWNER")


class TestClaims:
    def test_claim_consumes_token_and_blocks_others(self, estate, econtent):
        assert estate["agents"]["a1"]["claim_tokens"] == 2
        put(estate, "a1", pos=(3, 3))
        s, events = step(estate, {"a1": [{"verb": "claim", "x": 3, "y": 3}]}, econtent)
        assert s["claims"]["3,3"]["owner"] == "a1"
        assert s["agents"]["a1"]["claim_tokens"] == 1
        assert of_type(events, "claimed")

        s["tiles"]["3,3"]["deposit"] = {"kind": "trees", "item": "wood", "qty": 5}
        put(s, "a2", pos=(3, 3))
        _, events = step(s, {"a2": [{"verb": "harvest"}]}, econtent)
        assert rejections(events, "a2", "R_NO_PERMISSION")

    def test_grant_allows_harvest(self, estate, econtent):
        estate["claims"]["3,3"] = {"owner": "a1", "granted": []}
        estate["tiles"]["3,3"]["deposit"] = {"kind": "trees", "item": "wood", "qty": 5}
        put(estate, "a2", pos=(3, 3))
        s, _ = step(estate, {"a1": [{"verb": "grant", "to": "a2", "x": 3, "y": 3}],
                             "a2": [{"verb": "harvest"}]}, econtent)
        # grant happens in the claims phase, before gather
        assert s["agents"]["a2"]["inventory"] == {"wood": 1}

    def test_already_claimed_and_unclaimable(self, estate, econtent):
        estate["claims"]["3,3"] = {"owner": "a2", "granted": []}
        put(estate, "a1", pos=(3, 3))
        _, events = step(estate, {"a1": [{"verb": "claim", "x": 3, "y": 3}]}, econtent)
        assert rejections(events, "a1", "R_ALREADY_CLAIMED")
        site = estate["project"]["site"]
        put(estate, "a1", pos=tuple(site))
        _, events = step(estate, {"a1": [{"verb": "claim", "x": site[0], "y": site[1]}]}, econtent)
        assert rejections(events, "a1", "R_UNCLAIMABLE")

    def test_upkeep_lapses_unpaid_claim(self, estate, econtent):
        estate["claims"]["3,3"] = {"owner": "a1", "granted": []}
        estate["agents"]["a1"]["inventory"] = {"wood": 1}
        s = estate
        lapses = []
        for _ in range(9):
            s, events = step(s, {}, econtent)
            lapses += of_type(events, "claim_lapsed")
        # paid once (1 wood at tick 3), lapsed at the next upkeep (tick 7)
        assert lapses and "3,3" not in s["claims"]
        assert s["agents"]["a1"]["inventory"] == {}
