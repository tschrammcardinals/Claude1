from tennis_arb.fees import FeeModel


def test_max_taker_fee_at_50c():
    f = FeeModel()
    # 100 contracts at 50c: 0.07 * 100 * 0.5 * 0.5 = $1.75 -> 175c
    assert f.taker_fee_cents(100, 50) == 175


def test_max_maker_fee_at_50c():
    f = FeeModel()
    # 100 contracts at 50c: 0.0175 * 100 * 0.5 * 0.5 = $0.4375 -> ceil to 44c
    assert f.maker_fee_cents(100, 50) == 44


def test_fee_drops_at_extremes():
    f = FeeModel()
    assert f.maker_fee_cents(100, 5) < f.maker_fee_cents(100, 50)
    assert f.maker_fee_cents(100, 95) < f.maker_fee_cents(100, 50)


def test_round_trip_net_per_contract_at_fair_50():
    f = FeeModel()
    # buy 47, sell 53 -> gross 6c, maker fees ~0.44c each side
    net = f.net_round_trip_cents_per_contract(47, 53, count=100)
    assert 5.0 <= net <= 5.5
