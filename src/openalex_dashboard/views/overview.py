from typing import Any, Dict

import pandas as pd
import plotly.express as px
import streamlit as st


def format_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except Exception:
        return "0"


def format_pct(value: Any) -> str:
    try:
        return f"{100 * float(value):.1f}%"
    except Exception:
        return "0.0%"


def render_overview_tab(bundle: Dict[str, Any], filtered: Dict[str, Any]) -> None:
    works = filtered["works"]
    authorships = filtered["authorships"]

    works_count = works["work_id"].nunique() if "work_id" in works.columns else len(works)
    total_citations = int(works["cited_by_count"].fillna(0).sum()) if "cited_by_count" in works.columns else 0
    oa_share = works["is_oa"].fillna(False).mean() if "is_oa" in works.columns and len(works) else 0
    sources_count = works["source_name"].dropna().nunique() if "source_name" in works.columns else 0
    external_authors = 0
    if "is_roster_person" in authorships.columns:
        external_authors = authorships.loc[authorships["is_roster_person"] == False, "author_id_short"].dropna().nunique()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Publications", format_int(works_count))
    c2.metric("Total citations", format_int(total_citations))
    c3.metric("OA share", format_pct(oa_share))
    c4.metric("Sources", format_int(sources_count))
    c5.metric("External collaborators", format_int(external_authors))

    left, right = st.columns(2)
    with left:
        st.subheader("Publications by year")
        pubs_by_year = (
            works.dropna(subset=["publication_year"])
            .groupby("publication_year", as_index=False)
            .agg(publications=("work_id", "nunique"))
            .sort_values("publication_year")
        )
        if pubs_by_year.empty:
            st.info("No publications for the current filters.")
        else:
            fig = px.bar(pubs_by_year, x="publication_year", y="publications", title="Publications by year")
            st.plotly_chart(fig, use_container_width=True)

    with right:
        st.subheader("Citations by publication year")
        cites_by_year = (
            works.dropna(subset=["publication_year"])
            .groupby("publication_year", as_index=False)
            .agg(total_citations=("cited_by_count", "sum"), mean_citations=("cited_by_count", "mean"))
            .sort_values("publication_year")
        )
        if cites_by_year.empty:
            st.info("No citation data for the current filters.")
        else:
            fig = px.line(
                cites_by_year,
                x="publication_year",
                y="total_citations",
                markers=True,
                title="Current citations summed by publication year",
            )
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Top publications")
    show_cols = [
        c
        for c in ["title", "publication_year", "source_name", "cited_by_count", "doi", "work_type"]
        if c in works.columns
    ]
    if show_cols:
        st.dataframe(
            works.sort_values("cited_by_count", ascending=False).head(20)[show_cols],
            use_container_width=True,
            hide_index=True,
        )
