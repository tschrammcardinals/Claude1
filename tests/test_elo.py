from tennis_arb.model.elo import EloModel


def test_initial_prob_is_half():
    m = EloModel()
    assert abs(m.prob("A", "B", "Hard") - 0.5) < 1e-9


def test_winner_rises_loser_falls():
    m = EloModel()
    for _ in range(20):
        m.update("A", "B", "Hard")
    assert m._get("A").overall > 1500
    assert m._get("B").overall < 1500
    assert m.prob("A", "B", "Hard") > 0.7


def test_surface_specialisation():
    m = EloModel(surface_alpha=0.8)
    for _ in range(30):
        m.update("Clay-Specialist", "Generalist", "Clay")
    p_clay = m.prob("Clay-Specialist", "Generalist", "Clay")
    p_grass = m.prob("Clay-Specialist", "Generalist", "Grass")
    assert p_clay > p_grass


def test_serialisation_roundtrip():
    m = EloModel()
    for _ in range(5):
        m.update("A", "B", "Hard")
    d = m.to_dict()
    m2 = EloModel.from_dict(d)
    assert abs(m2.prob("A", "B", "Hard") - m.prob("A", "B", "Hard")) < 1e-9
