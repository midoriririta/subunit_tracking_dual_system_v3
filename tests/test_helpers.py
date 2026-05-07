import pandas as pd

from src.openalex_dashboard.data import explode_json_list_column, safe_json_loads
from src.openalex_dashboard.filters import allowed_confidence_levels


def test_safe_json_loads_list_string():
    assert safe_json_loads('["UK", "US"]') == ["UK", "US"]


def test_explode_json_list_column():
    df = pd.DataFrame({"country_codes_json": ['["GB", "US"]', '[]', None]})
    out = explode_json_list_column(df, "country_codes_json", "country_code")
    assert out["country_code"].tolist() == ["GB", "US"]


def test_confidence_filter_default_and_low():
    assert allowed_confidence_levels(False, False) == ["high"]
    assert allowed_confidence_levels(True, False) == ["high", "medium"]
    assert allowed_confidence_levels(False, True) == ["high", "medium", "low"]
