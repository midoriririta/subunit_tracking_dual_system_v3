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


def render_data_quality_tab(bundle: Dict[str, Any], filtered: Dict[str, Any]) -> None:
    people = bundle["people"]
    works = bundle["works"]
    authorships = bundle["authorships"]
    institutions = bundle["institutions"]
    topics_long = bundle["topics_long"]
    roster_works = bundle.get("roster_works", pd.DataFrame())
    confidence_col = bundle.get("confidence_col")

    st.subheader("Roster / matching quality")
    total_roster_rows = len(people)
    mapped_ids = people["openalex_author_id_short"].notna().sum() if "openalex_author_id_short" in people.columns else 0
    matched_profiles = people["author_display_name"].notna().sum() if "author_display_name" in people.columns else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("Roster rows", format_int(total_roster_rows))
    c2.metric("Rows with OpenAlex ID", format_int(mapped_ids))
    c3.metric("Rows matched to author profile", format_int(matched_profiles))

    if confidence_col and confidence_col in people.columns:
        st.subheader(f"Confidence distribution: {confidence_col}")
        conf_df = (
            people[confidence_col]
            .fillna("Missing")
            .astype(str)
            .value_counts(dropna=False)
            .rename_axis(confidence_col)
            .reset_index(name="rows")
        )
        fig = px.bar(conf_df, x=confidence_col, y="rows", title="Confidence labels")
        st.plotly_chart(fig, use_container_width=True)

    if not roster_works.empty and "paper_confidence" in roster_works.columns:
        st.subheader("Paper-level confidence distribution")
        paper_conf_df = (
            roster_works["paper_confidence"]
            .fillna("Missing")
            .astype(str)
            .value_counts(dropna=False)
            .rename_axis("paper_confidence")
            .reset_index(name="rows")
        )
        fig = px.bar(paper_conf_df, x="paper_confidence", y="rows", title="Paper-level confidence labels")
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Coverage checks")
    coverage = pd.DataFrame(
        {
            "table": ["people", "works", "authorships", "institutions", "topics_long", "roster_works"],
            "rows": [len(people), len(works), len(authorships), len(institutions), len(topics_long), len(roster_works)],
        }
    )
    st.dataframe(coverage, use_container_width=True, hide_index=True)

    if "publication_year" in works.columns:
        st.write(f"Missing publication_year in works: {100 * works['publication_year'].isna().mean():.1f}%")
    if "source_name" in works.columns:
        st.write(f"Missing source_name in works: {100 * works['source_name'].isna().mean():.1f}%")
    if "topics_json" in works.columns:
        st.write(f"Missing topics_json in works: {100 * works['topics_json'].isna().mean():.1f}%")
