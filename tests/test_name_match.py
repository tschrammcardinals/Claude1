from tennis_arb.name_match import parse_title, resolve_pair


def test_parse_title_vs():
    assert parse_title("Carlos Alcaraz vs. Jannik Sinner") == (
        "Carlos Alcaraz",
        "Jannik Sinner",
    )


def test_parse_title_unparseable():
    assert parse_title("Tennis Match Outcome") is None


def test_resolve_pair_fuzzy():
    cands = ["Carlos Alcaraz", "Jannik Sinner", "Novak Djokovic"]
    a, b = resolve_pair("C. Alcaraz", "J Sinner", cands)
    assert a == "Carlos Alcaraz"
    assert b == "Jannik Sinner"
