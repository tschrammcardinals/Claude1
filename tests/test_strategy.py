from tennis_arb.config import StrategyConfig
from tennis_arb.fees import FeeModel
from tennis_arb.strategy import OrderbookTouch, Strategy, parse_orderbook


def _strategy(**kw):
    cfg = StrategyConfig(**kw)
    return Strategy(cfg, FeeModel())


def test_initial_bids_below_fair():
    s = _strategy(bid_offset_cents=4, ask_offset_cents=3, target_net_per_contract_cents=3.0)
    intents = s.initial_bids(60, OrderbookTouch(), count=10)
    by_side = {i.side: i for i in intents}
    assert by_side["yes"].price_cents <= 56
    assert by_side["no"].price_cents <= 36
    for i in intents:
        assert i.action == "buy"
        assert i.count == 10


def test_optimizer_widens_when_target_unmet():
    # Offsets of 1c each give 2c gross at fair=50c, ~0.88c fees per round
    # trip, net ~1.1c — below a 3c target. Optimizer must widen until net
    # clears the target.
    s = _strategy(bid_offset_cents=1, ask_offset_cents=1, target_net_per_contract_cents=3.0)
    intents = s.initial_bids(50, OrderbookTouch(), count=100)
    yes = [i for i in intents if i.side == "yes"][0]
    # Starting (49,51) -> widens to (48,52). Bid is at most 49 - some_widen.
    assert yes.price_cents < 49


def test_initial_bids_skipped_outside_band():
    s = _strategy(min_fair_price_cents=15, max_fair_price_cents=85)
    assert s.initial_bids(95, OrderbookTouch(), count=10) == []
    assert s.initial_bids(5, OrderbookTouch(), count=10) == []


def test_exit_ask_above_fair():
    s = _strategy(bid_offset_cents=4, ask_offset_cents=3, target_net_per_contract_cents=3.0)
    yes_ask = s.exit_ask("yes", 60, OrderbookTouch())
    no_ask = s.exit_ask("no", 60, OrderbookTouch())
    assert yes_ask is not None and yes_ask.price_cents >= 63
    assert no_ask is not None and no_ask.price_cents >= 43


def test_post_only_safety_below_ask():
    # If the touch already has an ask at 53c, a yes bid of 56c would cross —
    # optimizer should cap at 52c and re-evaluate.
    s = _strategy(bid_offset_cents=4, ask_offset_cents=3, target_net_per_contract_cents=2.0)
    intents = s.initial_bids(60, OrderbookTouch(yes_ask=53), count=10)
    yes = [i for i in intents if i.side == "yes"][0]
    assert yes.price_cents <= 52


def test_parse_orderbook():
    raw = {"orderbook": {"yes": [[55, 100], [54, 200]], "no": [[44, 50], [43, 75]]}}
    ob = parse_orderbook(raw)
    assert ob.yes_bid == 55
    assert ob.no_bid == 44
