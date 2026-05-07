from typing import Any, Dict

import pandas as pd
import streamlit as st


def render_explorer_tab(bundle: Dict[str, Any], filtered: Dict[str, Any]) -> None:
    works = filtered["works"].copy()
    roster_works = filtered.get("roster_works", pd.DataFrame()).copy()

    st.subheader("Publications explorer")
    if "doi" in works.columns:
        works["doi_url"] = works["doi"].apply(
            lambda value: f"https://doi.org/{value}" if pd.notna(value) and str(value).strip() else None
        )

    if not roster_works.empty and "paper_confidence" in roster_works.columns:
        confidence_summary = (
            roster_works.groupby("work_id", as_index=False)
            .agg(
                paper_confidence=("paper_confidence", lambda s: "; ".join(sorted(set(map(str, s))))),
                linked_staff=("staff_name", lambda s: "; ".join(sorted(set(x for x in map(str, s) if x and x != "nan")))),
            )
        )
        works = works.merge(confidence_summary, on="work_id", how="left")

    columns = [
        col
        for col in [
            "title",
            "publication_year",
            "publication_date",
            "source_name",
            "source_type",
            "work_type",
            "cited_by_count",
            "is_oa",
            "oa_status",
            "paper_confidence",
            "linked_staff",
            "doi",
            "doi_url",
            "work_id",
        ]
        if col in works.columns
    ]

    sort_options = [col for col in ["publication_year", "cited_by_count", "source_name", "title"] if col in works.columns]
    sort_col = st.selectbox("Sort table by", options=sort_options, index=1 if "cited_by_count" in sort_options else 0)
    ascending = st.checkbox("Sort ascending", value=False)
    search_text = st.text_input("Search title contains")
    if search_text and "title" in works.columns:
        works = works[works["title"].fillna("").str.contains(search_text, case=False, na=False)]
    works = works.sort_values(sort_col, ascending=ascending)
    st.dataframe(works[columns], use_container_width=True, hide_index=True)
