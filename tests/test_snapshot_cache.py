from src.openalex_dashboard.data import load_bundle


def test_bundled_caches_exist_and_load():
    demo = load_bundle("demography")
    ndph = load_bundle("ndph")
    assert len(demo["people"]) > 0
    assert len(ndph["people"]) > 0
    assert "paper_confidence" in demo["roster_works"].columns
    assert "paper_confidence" in ndph["roster_works"].columns
