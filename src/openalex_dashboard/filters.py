from __future__ import annotations

from typing import Any, Dict

import pandas as pd

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    class _DummyStreamlit:
        def __getattr__(self, name):
            def _missing(*args, **kwargs):
                raise RuntimeError("Streamlit is required for UI rendering.")
            return _missing
    st = _DummyStreamlit()

CONFIDENCE_LEVELS = ["high", "medium", "low"]


def _normalise_confidence(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"high", "medium", "low"}:
        return text
    if text in {"med", "middle"}:
        return "medium"
    return "low" if text else "low"


def allowed_confidence_levels(include_medium: bool, include_low: bool) -> list[str]:
    levels = ["high"]
    if include_medium or include_low:
        levels.append("medium")
    if include_low:
        levels.append("low")
    return levels


def render_sidebar_filters(bundle: Dict[str, Any]) -> Dict[str, Any]:
    works = bundle["works"]
    authorships = bundle["authorships"]
    roster_works = bundle.get("roster_works", pd.DataFrame())
    people = bundle["people"]
    person_name_col = bundle.get("person_name_col")

    valid_years = works["publication_year"].dropna().astype(int) if "publication_year" in works.columns else []
    year_min = int(valid_years.min()) if len(valid_years) else 2000
    year_max = int(valid_years.max()) if len(valid_years) else 2026

    roster_options: list[str] = []
    if not roster_works.empty and "staff_name" in roster_works.columns:
        roster_options = sorted(roster_works["staff_name"].dropna().astype(str).unique().tolist())
    elif "roster_person_name" in authorships.columns:
        roster_options = sorted(
            authorships.loc[authorships["roster_person_name"].notna(), "roster_person_name"]
            .astype(str)
            .unique()
            .tolist()
        )
    elif person_name_col:
        roster_options = sorted(people.loc[people[person_name_col].notna(), person_name_col].astype(str).unique().tolist())

    source_type_options: list[str] = []
    if "source_type" in works.columns:
        source_type_options = sorted(works["source_type"].dropna().astype(str).unique().tolist())

    with st.sidebar:
        st.header("Filters")
        year_range = st.slider(
            "Publication year range",
            min_value=year_min,
            max_value=year_max,
            value=(year_min, year_max),
        )
        selected_people = st.multiselect("Selected people", options=roster_options, default=[])
        selected_source_types = st.multiselect("Source type", options=source_type_options, default=source_type_options)
        oa_only = st.checkbox("Open access only", value=False)
        min_citations = st.number_input("Minimum cited_by_count", min_value=0, value=0, step=1)

        st.markdown("**Publication confidence**")
        include_medium = st.checkbox(
            "Enable medium confidence papers",
            value=False,
            help="Default is high-confidence papers only. Medium keeps papers with a credible author match but weaker paper-level evidence.",
        )
        include_low = st.checkbox(
            "Enable medium and low confidence papers",
            value=False,
            help="Use this for auditing or manual review. It is intentionally off by default.",
        )
        if include_low and not include_medium:
            include_medium = True

    return {
        "year_range": year_range,
        "selected_people": selected_people,
        "selected_source_types": selected_source_types,
        "oa_only": oa_only,
        "min_citations": min_citations,
        "confidence_levels": allowed_confidence_levels(include_medium, include_low),
    }


def apply_global_filters(bundle: Dict[str, Any], filters: Dict[str, Any]) -> Dict[str, Any]:
    works = bundle["works"].copy()
    authorships = bundle["authorships"].copy()
    topics_long = bundle["topics_long"].copy()
    roster_works = bundle.get("roster_works", pd.DataFrame()).copy()

    year_start, year_end = filters["year_range"]
    if "publication_year" in works.columns:
        works = works[works["publication_year"].fillna(-999999).between(year_start, year_end)]

    selected_source_types = filters["selected_source_types"]
    if selected_source_types and "source_type" in works.columns:
        works = works[works["source_type"].isin(selected_source_types)]

    if filters["oa_only"] and "is_oa" in works.columns:
        works = works[works["is_oa"] == True]

    if "cited_by_count" in works.columns:
        works = works[works["cited_by_count"].fillna(0) >= filters["min_citations"]]

    selected_people = filters["selected_people"]
    if selected_people:
        if not roster_works.empty and "staff_name" in roster_works.columns:
            keep_work_ids = roster_works.loc[roster_works["staff_name"].isin(selected_people), "work_id"].dropna().unique()
            works = works[works["work_id"].isin(keep_work_ids)]
        elif "roster_person_name" in authorships.columns:
            keep_work_ids = authorships.loc[
                authorships["roster_person_name"].isin(selected_people), "work_id"
            ].dropna().unique()
            works = works[works["work_id"].isin(keep_work_ids)]

    keep_work_ids = set(works["work_id"].dropna().tolist()) if "work_id" in works.columns else set()
    if not roster_works.empty:
        roster_works = roster_works[roster_works["work_id"].isin(keep_work_ids)].copy()
        if "paper_confidence" in roster_works.columns:
            roster_works["paper_confidence_norm"] = roster_works["paper_confidence"].map(_normalise_confidence)
            roster_works = roster_works[roster_works["paper_confidence_norm"].isin(filters["confidence_levels"])]
            keep_work_ids = set(roster_works["work_id"].dropna().tolist())
            works = works[works["work_id"].isin(keep_work_ids)]

    authorships = authorships[authorships["work_id"].isin(keep_work_ids)].copy() if "work_id" in authorships.columns else authorships
    topics_long = topics_long[topics_long["work_id"].isin(keep_work_ids)].copy() if "work_id" in topics_long.columns else topics_long

    return {"works": works, "authorships": authorships, "topics_long": topics_long, "roster_works": roster_works}
