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


def render_domains_sources_tab(bundle: Dict[str, Any], filtered: Dict[str, Any]) -> None:
    works = filtered["works"]
    topics_long = filtered["topics_long"]

    left, right = st.columns(2)
    with left:
        st.subheader("Top domains")
        if not topics_long.empty and "domain_name" in topics_long.columns:
            top_domains = (
                topics_long.dropna(subset=["domain_name"])
                .groupby("domain_name", as_index=False)
                .agg(works=("work_id", "nunique"))
                .sort_values("works", ascending=False)
                .head(15)
            )
            if top_domains.empty:
                st.info("No domain data for the current filters.")
            else:
                fig = px.bar(top_domains, x="works", y="domain_name", orientation="h", title="Top domains")
                fig.update_layout(yaxis={"categoryorder": "total ascending"})
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("topics_long.parquet has no domain_name data.")

    with right:
        st.subheader("Top fields")
        if not topics_long.empty and "field_name" in topics_long.columns:
            top_fields = (
                topics_long.dropna(subset=["field_name"])
                .groupby("field_name", as_index=False)
                .agg(works=("work_id", "nunique"))
                .sort_values("works", ascending=False)
                .head(15)
            )
            if top_fields.empty:
                st.info("No field data for the current filters.")
            else:
                fig = px.bar(top_fields, x="works", y="field_name", orientation="h", title="Top fields")
                fig.update_layout(yaxis={"categoryorder": "total ascending"})
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("topics_long.parquet has no field_name data.")

    st.subheader("Top sources")
    if "source_name" in works.columns:
        top_sources = (
            works.dropna(subset=["source_name"])
            .groupby(["source_name", "source_type"], as_index=False)
            .agg(publications=("work_id", "nunique"), total_citations=("cited_by_count", "sum"))
            .sort_values(["publications", "total_citations"], ascending=False)
            .head(20)
        )
        st.dataframe(top_sources, use_container_width=True, hide_index=True)
    else:
        st.info("works.parquet has no source_name column.")
