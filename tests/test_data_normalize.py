from tennis_arb.model.data import (
    _sack_split,
    _td_split,
    build_td_to_sackmann_map,
    normalize_td_name,
)


def test_td_split_simple():
    assert _td_split("Tiafoe F.") == ("tiafoe", "F")


def test_td_split_multi_word_lastname():
    assert _td_split("Ugo Carabelli C.") == ("ugo carabelli", "C")


def test_td_split_hyphenated():
    # Hyphens become spaces; "Auger-Aliassime F." -> ("auger aliassime", "F")
    assert _td_split("Auger-Aliassime F.") == ("auger aliassime", "F")


def test_sack_split():
    assert _sack_split("Frances Tiafoe") == ("tiafoe", "F")
    assert _sack_split("Camilo Ugo Carabelli") == ("ugo carabelli", "C")
    assert _sack_split("Felix Auger Aliassime") == ("auger aliassime", "F")


def test_normalize_round_trip():
    sack = ["Frances Tiafoe", "Carlos Alcaraz", "Felix Auger Aliassime"]
    lookup = build_td_to_sackmann_map(sack)
    assert normalize_td_name("Tiafoe F.", lookup) == "Frances Tiafoe"
    assert normalize_td_name("Alcaraz C.", lookup) == "Carlos Alcaraz"
    assert normalize_td_name("Auger-Aliassime F.", lookup) == "Felix Auger Aliassime"


def test_normalize_unmapped_passes_through():
    lookup = build_td_to_sackmann_map(["Carlos Alcaraz"])
    assert normalize_td_name("BrandNewPlayer X.", lookup) == "BrandNewPlayer X."
