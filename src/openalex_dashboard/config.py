from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CACHE_DIR = DATA_DIR / "cache"
OUTPUT_DIR = DATA_DIR / "outputs"

BASE_PAGE_TITLE = "Department Publications Dashboard"
PAGE_TITLE = BASE_PAGE_TITLE

OPENALEX_MAILTO_ENV = "OPENALEX_MAILTO"
DEFAULT_OPENALEX_MAILTO = os.environ.get(OPENALEX_MAILTO_ENV, "").strip()

# The data still has two switchable views, but the selector now displays them as
# a hierarchy: NDPH Department -> Demographic Science Unit. The Demographic
# Science Unit is a subunit of NDPH, not a parallel department-level option.
DATASET_CONFIGS = {
    "demography": {
        "key": "demography",
        "label": "Demographic Science Unit",
        "navigation_label": "\u00a0\u00a0\u00a0\u00a0↳ Demographic Science Unit",
        "parent_key": "ndph",
        "parent_label": "NDPH Department",
        "hierarchy_level": 1,
        "display_order": 20,
        "suffix": "",
        "title": "Demographic Science Unit Publications Dashboard",
        "caption": (
            "Dashboard using OpenAlex data for people in the Demographic Science Unit, "
            "shown as a subunit of the Nuffield Department of Population Health."
        ),
        "default_staff_csv": RAW_DIR / "demography_openalex_people.csv",
        "legacy_staff_csv": RAW_DIR / "demography_openalex_people.csv",
    },
    "ndph": {
        "key": "ndph",
        "label": "NDPH Department",
        "navigation_label": "NDPH Department",
        "parent_key": None,
        "parent_label": None,
        "hierarchy_level": 0,
        "display_order": 10,
        "suffix": "_ndph",
        "title": "NDPH Department Publications Dashboard",
        "caption": "Dashboard using OpenAlex data for people in the Nuffield Department of Population Health.",
        "default_staff_csv": RAW_DIR / "ndph_openalex_people.csv",
        "legacy_staff_csv": RAW_DIR / "ndph_openalex_people.csv",
    },
}

# Keep the Demographic Science Unit as the default so existing public links and
# the current Streamlit query behaviour remain backwards-compatible.
DEFAULT_DATASET_KEY = "demography"

# Keep the original required cache set so older caches still load.
# Newer builds also include author_candidates and roster_works for confidence filtering.
REQUIRED_CACHE_TABLES = ["people", "works", "authorships", "institutions", "topics_long"]
OPTIONAL_CACHE_TABLES = ["author_candidates", "roster_works"]
REQUIRED_AGGREGATES = [
    "agg_publications_by_year",
    "agg_citations_by_pubyear",
    "agg_collaborator_countries_by_year",
    "agg_domains_by_year",
    "agg_sources_by_year",
    "agg_confidence_by_year",
]

OXFORD_TERMS = [
    "university of oxford",
    "oxford university",
    "department of population health",
    "nuffield department of population health",
    "ndph",
    "demographic science unit",
    "demography",
    "leverhulme centre for demographic science",
    "lcds",
]


def get_dataset_config(dataset_key: str | None) -> dict:
    dataset_key = (dataset_key or DEFAULT_DATASET_KEY).lower()
    return DATASET_CONFIGS.get(dataset_key, DATASET_CONFIGS[DEFAULT_DATASET_KEY]).copy()


def get_dataset_display_order() -> list[str]:
    """Return dataset keys in parent-before-child display order."""
    return sorted(
        DATASET_CONFIGS.keys(),
        key=lambda key: (
            DATASET_CONFIGS[key].get("display_order", 999),
            DATASET_CONFIGS[key].get("hierarchy_level", 0),
            DATASET_CONFIGS[key].get("label", key),
        ),
    )
