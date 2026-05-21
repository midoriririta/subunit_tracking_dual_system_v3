from __future__ import annotations

from itertools import combinations
from typing import Any, Dict

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pycountry
import streamlit as st

from src.openalex_dashboard.data import explode_json_list_column

try:
    import networkx as nx
except Exception:  # pragma: no cover
    nx = None


def format_int(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except Exception:
        return "0"


def alpha2_to_country(code: Any):
    if not code or pd.isna(code):
        return None
    try:
        return pycountry.countries.get(alpha_2=str(code).upper())
    except Exception:
        return None


def alpha2_to_alpha3(code: Any):
    country = alpha2_to_country(code)
    return getattr(country, "alpha_3", None) if country else None


def alpha2_to_name(code: Any) -> str | None:
    country = alpha2_to_country(code)
    return getattr(country, "name", None) if country else None


def _external_authorships(authorships: pd.DataFrame) -> pd.DataFrame:
    if authorships.empty:
        return authorships.copy()

    external = authorships.copy()
    if "is_roster_person" in external.columns:
        external = external[~external["is_roster_person"].fillna(False)].copy()
    return external


def _country_summary(external: pd.DataFrame) -> pd.DataFrame:
    country_df = explode_json_list_column(external, "country_codes_json", "country_code")
    if country_df.empty:
        return pd.DataFrame()

    required_cols = {"country_code", "work_id"}
    if not required_cols.issubset(country_df.columns):
        return pd.DataFrame()

    named_aggs: dict[str, tuple[str, str]] = {
        "external_authorship_rows": ("work_id", "size"),
        "collaborator_works": ("work_id", "nunique"),
    }

    if "author_id_short" in country_df.columns:
        named_aggs["unique_external_authors"] = ("author_id_short", "nunique")
    else:
        country_df["author_id_short"] = None
        named_aggs["unique_external_authors"] = ("author_id_short", "nunique")

    country_summary = (
        country_df.groupby("country_code", as_index=False)
        .agg(**named_aggs)
        .sort_values("collaborator_works", ascending=False)
    )
    country_summary["country_code"] = country_summary["country_code"].astype(str).str.upper()
    country_summary["country_name"] = country_summary["country_code"].apply(alpha2_to_name)
    country_summary["country_name"] = country_summary["country_name"].fillna(country_summary["country_code"])
    country_summary["iso_alpha"] = country_summary["country_code"].apply(alpha2_to_alpha3)
    return country_summary


def _render_country_map(country_summary: pd.DataFrame) -> None:
    st.subheader("Collaborator works by country")

    if country_summary.empty:
        st.info("No external collaborator country data for the current filters.")
        return

    map_df = country_summary[country_summary["iso_alpha"].notna()].copy()
    if map_df.empty:
        st.info("No mappable country codes after conversion.")
        st.dataframe(country_summary.head(25), use_container_width=True, hide_index=True)
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Collaborator countries", format_int(map_df["iso_alpha"].nunique()))
    c2.metric("Collaborator works", format_int(map_df["collaborator_works"].sum()))
    c3.metric("Unique external authors", format_int(map_df["unique_external_authors"].sum()))

    fig = px.choropleth(
        map_df,
        locations="iso_alpha",
        color="collaborator_works",
        hover_name="country_name",
        custom_data=[
            "country_name",
            "country_code",
            "collaborator_works",
            "unique_external_authors",
            "external_authorship_rows",
        ],
        color_continuous_scale="YlGnBu",
        projection="natural earth",
    )
    fig.update_traces(
        marker_line_color="rgba(255,255,255,0.72)",
        marker_line_width=0.45,
        hovertemplate=(
            "<b>%{customdata[0]}</b> (%{customdata[1]})<br>"
            "Collaborator works: %{customdata[2]:,}<br>"
            "Unique external authors: %{customdata[3]:,}<br>"
            "External authorship rows: %{customdata[4]:,}"
            "<extra></extra>"
        ),
    )
    fig.update_geos(
        showframe=False,
        showcoastlines=True,
        coastlinecolor="rgba(84,105,120,0.45)",
        showcountries=True,
        countrycolor="rgba(255,255,255,0.7)",
        showland=True,
        landcolor="rgba(244,247,250,1)",
        showocean=True,
        oceancolor="rgba(228,239,248,1)",
        bgcolor="rgba(0,0,0,0)",
        lataxis_showgrid=False,
        lonaxis_showgrid=False,
    )
    fig.update_layout(
        height=560,
        margin=dict(l=0, r=0, t=12, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        coloraxis_colorbar=dict(
            title="Works",
            thickness=14,
            len=0.62,
            y=0.48,
            outlinewidth=0,
        ),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "Countries are counted from external co-author affiliation country codes in the currently filtered publication set."
    )

    left, right = st.columns([1.15, 1])
    with left:
        top_countries = map_df.head(15).sort_values("collaborator_works", ascending=True)
        fig_bar = px.bar(
            top_countries,
            x="collaborator_works",
            y="country_name",
            orientation="h",
            text="collaborator_works",
            labels={"country_name": "Country", "collaborator_works": "Collaborator works"},
            title="Top collaborator countries",
        )
        fig_bar.update_traces(textposition="outside", cliponaxis=False)
        fig_bar.update_layout(
            height=430,
            margin=dict(l=0, r=20, t=48, b=0),
            yaxis=dict(title=None),
            xaxis=dict(title="Collaborator works", rangemode="tozero"),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    with right:
        show_cols = [
            "country_name",
            "country_code",
            "collaborator_works",
            "unique_external_authors",
            "external_authorship_rows",
        ]
        st.dataframe(
            country_summary[show_cols].head(25),
            use_container_width=True,
            hide_index=True,
            column_config={
                "country_name": "Country",
                "country_code": "Code",
                "collaborator_works": "Works",
                "unique_external_authors": "External authors",
                "external_authorship_rows": "Authorship rows",
            },
        )


def _clean_node_name(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text if text else None


def _add_node_id(df: pd.DataFrame, prefer_roster_name: bool) -> pd.DataFrame:
    out = df.copy()

    fallback = pd.Series([None] * len(out), index=out.index, dtype="object")
    if "author_id_short" in out.columns:
        fallback = out["author_id_short"]

    if prefer_roster_name and "roster_person_name" in out.columns:
        node_id = out["roster_person_name"]
        if "author_name" in out.columns:
            node_id = node_id.fillna(out["author_name"])
        node_id = node_id.fillna(fallback)
    else:
        if "author_name" in out.columns:
            node_id = out["author_name"].fillna(fallback)
        else:
            node_id = fallback

    out["node_id"] = node_id.apply(_clean_node_name)
    return out[out["node_id"].notna()].copy()


def _node_totals(edges: pd.DataFrame) -> pd.DataFrame:
    if edges.empty:
        return pd.DataFrame(columns=["node", "total_shared_works"])

    degree_weight = pd.concat(
        [
            edges[["source", "shared_works"]].rename(columns={"source": "node"}),
            edges[["target", "shared_works"]].rename(columns={"target": "node"}),
        ],
        ignore_index=True,
    )
    return degree_weight.groupby("node", as_index=False).agg(total_shared_works=("shared_works", "sum"))


def _build_collaboration_edges(
    authorships: pd.DataFrame,
    max_external_nodes: int = 35,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {"work_id", "author_id_short", "author_name", "is_roster_person"}
    if authorships.empty or not required.issubset(authorships.columns):
        return pd.DataFrame(), pd.DataFrame()

    roster = authorships[authorships["is_roster_person"].fillna(False)].copy()
    external = authorships[~authorships["is_roster_person"].fillna(False)].copy()
    if roster.empty or external.empty:
        return pd.DataFrame(), pd.DataFrame()

    roster = _add_node_id(roster, prefer_roster_name=True)
    external = _add_node_id(external, prefer_roster_name=False)
    if roster.empty or external.empty:
        return pd.DataFrame(), pd.DataFrame()

    pair_rows = []
    external_by_work = {work_id: group for work_id, group in external.groupby("work_id")}
    for work_id, rgrp in roster.groupby("work_id"):
        egrp = external_by_work.get(work_id)
        if egrp is None or egrp.empty:
            continue

        sources = sorted(set(rgrp["node_id"].dropna().astype(str)))
        targets = sorted(set(egrp["node_id"].dropna().astype(str)))
        for source in sources:
            for target in targets:
                if source and target and source != target:
                    pair_rows.append({"source": source, "target": target, "work_id": work_id})

    if not pair_rows:
        return pd.DataFrame(), pd.DataFrame()

    pairs = pd.DataFrame(pair_rows)
    edges = (
        pairs.groupby(["source", "target"], as_index=False)
        .agg(shared_works=("work_id", "nunique"))
        .sort_values("shared_works", ascending=False)
    )

    top_external = (
        edges.groupby("target", as_index=False)["shared_works"]
        .sum()
        .nlargest(max_external_nodes, "shared_works")
    )
    edges = edges[edges["target"].isin(top_external["target"])].copy()

    nodes = pd.DataFrame({"node": sorted(set(edges["source"]).union(edges["target"]))})
    roster_nodes = set(edges["source"])
    nodes["kind"] = nodes["node"].apply(lambda x: "Roster" if x in roster_nodes else "External collaborator")
    nodes = nodes.merge(_node_totals(edges), on="node", how="left")
    nodes["total_shared_works"] = nodes["total_shared_works"].fillna(0)
    return nodes, edges


def _build_internal_collaboration_edges(
    authorships: pd.DataFrame,
    max_edges: int = 60,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {"work_id", "is_roster_person"}
    if authorships.empty or not required.issubset(authorships.columns):
        return pd.DataFrame(), pd.DataFrame()

    roster = authorships[authorships["is_roster_person"].fillna(False)].copy()
    if roster.empty:
        return pd.DataFrame(), pd.DataFrame()

    roster = _add_node_id(roster, prefer_roster_name=True)
    if roster.empty:
        return pd.DataFrame(), pd.DataFrame()

    pair_rows = []
    for work_id, group in roster.groupby("work_id"):
        staff_names = sorted(set(group["node_id"].dropna().astype(str)))
        if len(staff_names) < 2:
            continue
        for source, target in combinations(staff_names, 2):
            if source and target and source != target:
                pair_rows.append({"source": source, "target": target, "work_id": work_id})

    if not pair_rows:
        return pd.DataFrame(), pd.DataFrame()

    pairs = pd.DataFrame(pair_rows)
    edges = (
        pairs.groupby(["source", "target"], as_index=False)
        .agg(shared_works=("work_id", "nunique"))
        .sort_values(["shared_works", "source", "target"], ascending=[False, True, True])
    )

    graph_edges = edges.head(max_edges).copy()
    nodes = pd.DataFrame({"node": sorted(set(graph_edges["source"]).union(graph_edges["target"]))})
    nodes["kind"] = "Internal staff"
    nodes = nodes.merge(_node_totals(graph_edges), on="node", how="left")
    nodes["total_shared_works"] = nodes["total_shared_works"].fillna(0)
    return nodes, edges


def _layout_network(nodes: pd.DataFrame, edges: pd.DataFrame, seed: int = 7) -> dict[str, tuple[float, float]]:
    if nx is not None:
        graph = nx.Graph()
        for _, row in nodes.iterrows():
            graph.add_node(row["node"], kind=row["kind"], weight=row["total_shared_works"])
        for _, row in edges.iterrows():
            graph.add_edge(row["source"], row["target"], weight=row["shared_works"])
        return nx.spring_layout(graph, seed=seed, k=0.9)

    import math

    ordered = nodes["node"].tolist()
    return {
        node: (
            math.cos(2 * math.pi * i / max(len(ordered), 1)),
            math.sin(2 * math.pi * i / max(len(ordered), 1)),
        )
        for i, node in enumerate(ordered)
    }


def _draw_network_figure(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    title: str,
    height: int = 650,
    seed: int = 7,
) -> None:
    plot_edges = edges[
        edges["source"].isin(nodes["node"]) & edges["target"].isin(nodes["node"])
    ].copy()
    if nodes.empty or plot_edges.empty:
        return

    pos = _layout_network(nodes, plot_edges, seed=seed)

    edge_x, edge_y = [], []
    for _, row in plot_edges.iterrows():
        x0, y0 = pos[row["source"]]
        x1, y1 = pos[row["target"]]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=edge_x,
            y=edge_y,
            mode="lines",
            line=dict(width=0.7, color="rgba(86, 105, 128, 0.28)"),
            hoverinfo="skip",
            showlegend=False,
        )
    )

    for kind, group in nodes.groupby("kind"):
        xs = [pos[node][0] for node in group["node"]]
        ys = [pos[node][1] for node in group["node"]]
        shared = group["total_shared_works"].fillna(0).astype(float)
        sizes = 12 + shared.clip(upper=35)
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="markers+text",
                text=group["node"],
                textposition="top center",
                customdata=shared,
                marker=dict(size=sizes, line=dict(width=1.2, color="white"), opacity=0.88),
                name=kind,
                hovertemplate=(
                    "<b>%{text}</b><br>"
                    f"Type: {kind}<br>"
                    "Total shared works: %{customdata:,}"
                    "<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        title=title,
        xaxis=dict(showgrid=False, zeroline=False, visible=False),
        yaxis=dict(showgrid=False, zeroline=False, visible=False),
        margin=dict(l=10, r=10, t=50, b=10),
        height=height,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_network(authorships: pd.DataFrame) -> None:
    st.subheader("Collaboration network")

    nodes, edges = _build_collaboration_edges(authorships)
    if nodes.empty or edges.empty:
        st.info("No external co-author network can be drawn for the current filters.")
        return

    _draw_network_figure(
        nodes=nodes,
        edges=edges,
        title="Roster staff connected to external co-authors",
        height=650,
        seed=7,
    )
    st.caption(
        "Edges represent shared works in the currently filtered publication set; node size increases with repeated collaboration."
    )


def _render_internal_network(authorships: pd.DataFrame) -> None:
    st.subheader("Internal staff collaboration network")

    nodes, edges = _build_internal_collaboration_edges(authorships)
    if nodes.empty or edges.empty:
        st.info("No internal staff-to-staff collaboration network can be drawn for the current filters.")
        return

    graph_edges = edges.head(60).copy()
    graph_nodes = pd.DataFrame({"node": sorted(set(graph_edges["source"]).union(graph_edges["target"]))})
    graph_nodes["kind"] = "Internal staff"
    graph_nodes = graph_nodes.merge(_node_totals(graph_edges), on="node", how="left")
    graph_nodes["total_shared_works"] = graph_nodes["total_shared_works"].fillna(0)

    _draw_network_figure(
        nodes=graph_nodes,
        edges=graph_edges,
        title="Internal roster staff connected by shared works",
        height=620,
        seed=11,
    )
    st.caption(
        "This section only counts collaborations where both authors are roster/internal staff in the selected dataset and current filters."
    )

    st.markdown("**Top internal collaborator pairs**")
    top_pairs = edges.head(30).rename(
        columns={
            "source": "staff_member_1",
            "target": "staff_member_2",
            "shared_works": "collaboration_count",
        }
    )
    st.dataframe(
        top_pairs,
        use_container_width=True,
        hide_index=True,
        column_config={
            "staff_member_1": "Internal staff member 1",
            "staff_member_2": "Internal staff member 2",
            "collaboration_count": "Shared works",
        },
    )


def render_collaborators_tab(bundle: Dict[str, Any], filtered: Dict[str, Any]) -> None:
    authorships = filtered["authorships"]
    external = _external_authorships(authorships)
    country_summary = _country_summary(external)

    _render_country_map(country_summary)

    st.subheader("Top external institutions")
    inst_df = explode_json_list_column(external, "institution_names_json", "institution_name_exploded")
    if inst_df.empty:
        st.info("No external institution data for the current filters.")
    else:
        top_insts = (
            inst_df.groupby("institution_name_exploded", as_index=False)
            .agg(
                external_authorship_rows=("work_id", "size"),
                collaborator_works=("work_id", "nunique"),
                unique_external_authors=("author_id_short", "nunique"),
            )
            .sort_values("collaborator_works", ascending=False)
            .head(25)
        )
        st.dataframe(
            top_insts,
            use_container_width=True,
            hide_index=True,
            column_config={
                "institution_name_exploded": "Institution",
                "external_authorship_rows": "Authorship rows",
                "collaborator_works": "Works",
                "unique_external_authors": "External authors",
            },
        )

    _render_network(authorships)
    _render_internal_network(authorships)
