import tempfile
from pathlib import Path

from tennis_arb.config import RiskConfig
from tennis_arb.risk import RiskManager
from tennis_arb.store import Store


def _store():
    tmp = Path(tempfile.mkdtemp()) / "s.sqlite"
    return Store(tmp)


def test_per_market_exposure_cap():
    r = RiskManager(RiskConfig(max_exposure_per_market=10.0), _store())
    ok, _ = r.can_place("T1", "yes", count=10, price_cents=50)  # $5
    assert ok
    r.record_fill("T1", "yes", 10, 50, "buy")
    ok, reason = r.can_place("T1", "yes", count=20, price_cents=50)  # +$10 -> $15
    assert not ok
    assert "per-market" in reason


def test_per_side_contract_cap():
    r = RiskManager(RiskConfig(max_contracts_per_side=50), _store())
    r.record_fill("T1", "yes", 50, 50, "buy")
    ok, reason = r.can_place("T1", "yes", count=1, price_cents=50)
    assert not ok
    assert "per-side" in reason
