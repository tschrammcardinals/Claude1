from tennis_arb.config import StrategyConfig
from tennis_arb.strategy import OrderbookTouch, Strategy, parse_orderbook


def test_initial_bids_below_fair():
    s = Strategy(StrategyConfig(edge_cents=4, initial_bid_offset_cents=2))
    intents = s.initial_bids(60, OrderbookTouch(), count=10)
    by_side = {i.side: i for i in intents}
    assert by_side["yes"].price_cents == 56  # 60 - 4
    assert by_side["no"].price_cents == 36   # (100-60) - 4
    for i in intents:
        assert i.action == "buy"
        assert i.count == 10


def test_initial_bids_skipped_outside_band():
    s = Strategy(StrategyConfig(min_fair_price_cents=15, max_fair_price_cents=85))
    assert s.initial_bids(95, OrderbookTouch(), count=10) == []
    assert s.initial_bids(5, OrderbookTouch(), count=10) == []


def test_exit_ask_above_fair():
    s = Strategy(StrategyConfig(ask_offset_cents=3))
    yes_ask = s.exit_ask("yes", 60)
    no_ask = s.exit_ask("no", 60)
    assert yes_ask is not None and yes_ask.price_cents == 63
    assert no_ask is not None and no_ask.price_cents == 43


def test_parse_orderbook():
    raw = {"orderbook": {"yes": [[55, 100], [54, 200]], "no": [[44, 50], [43, 75]]}}
    ob = parse_orderbook(raw)
    assert ob.yes_bid == 55
    assert ob.no_bid == 44
