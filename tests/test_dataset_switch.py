from pathlib import Path

from src.openalex_dashboard.config import get_dataset_config
from src.openalex_dashboard.data import resolve_cache_paths


def test_dataset_config_suffixes():
    assert get_dataset_config("demography")["suffix"] == ""
    assert get_dataset_config("ndph")["suffix"] == "_ndph"


def test_demography_title_uses_unit_name():
    assert "Demographic Science Unit" in get_dataset_config("demography")["title"]


def test_resolve_cache_paths_uses_suffix(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    agg_dir = cache_dir / "aggregates"
    agg_dir.mkdir(parents=True)
    paths = resolve_cache_paths("ndph", cache_dir)
    assert paths["required"]["people"].name == "people_ndph.parquet"
    assert paths["aggregate_paths"]["agg_domains_by_year"].name == "agg_domains_by_year_ndph.parquet"
    assert paths["optional"]["roster_works"].name == "roster_works_ndph.parquet"
