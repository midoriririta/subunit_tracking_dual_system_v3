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


def alpha2_to_alpha3(code):
    if not code or pd.isna(code):
        return None
    try:
        return pycountry.countries.get(alpha_2=str(code).upper()).alpha_3
    except Exception:
        return None


def _build_collaboration_edges(authorships: pd.DataFrame, max_external_nodes: int = 35) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {"work_id", "author_id_short", "author_name", "is_roster_person"}
    if authorships.empty or not required.issubset(authorships.columns):
        return pd.DataFrame(), pd.DataFrame()

    roster = authorships[authorships["is_roster_person"].fillna(False)].copy()
    external = authorships[~authorships["is_roster_person"].fillna(False)].copy()
    if roster.empty or external.empty:
        return pd.DataFrame(), pd.DataFrame()

    roster["node_id"] = roster["roster_person_name"].fillna(roster["author_name"]).fillna(roster["author_id_short"])
    external["node_id"] = external["author_name"].fillna(external["author_id_short"])

    pair_rows = []
    for work_id, rgrp in roster.groupby("work_id"):
        egrp = external[external["work_id"] == work_id]
        if egrp.empty:
            continue
        for source in sorted(set(rgrp["node_id"].dropna().astype(str))):
            for target in sorted(set(egrp["node_id"].dropna().astype(str))):
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
    top_external = edges.groupby("target", as_index=False)["shared_works"].sum().nlargest(max_external_nodes, "shared_works")
    edges = edges[edges["target"].isin(top_external["target"])]

    nodes = pd.DataFrame({"node": sorted(set(edges["source"]).union(edges["target"]))})
    roster_nodes = set(edges["source"])
    nodes["kind"] = nodes["node"].apply(lambda x: "Roster" if x in roster_nodes else "External collaborator")
    degree_weight = pd.concat(
        [
            edges[["source", "shared_works"]].rename(columns={"source": "node"}),
            edges[["target", "shared_works"]].rename(columns={"target": "node"}),
        ]
    )
    nodes = nodes.merge(degree_weight.groupby("node", as_index=False).agg(total_shared_works=("shared_works", "sum")), on="node", how="left")
    return nodes, edges


def _render_network(authorships: pd.DataFrame) -> None:
    st.subheader("Collaboration network")
    nodes, edges = _build_collaboration_edges(authorships)
    if nodes.empty or edges.empty:
        st.info("No external co-author network can be drawn for the current filters.")
        return

    if nx is not None:
        graph = nx.Graph()
        for _, row in nodes.iterrows():
            graph.add_node(row["node"], kind=row["kind"], weight=row["total_shared_works"])
        for _, row in edges.iterrows():
            graph.add_edge(row["source"], row["target"], weight=row["shared_works"])
        pos = nx.spring_layout(graph, seed=7, k=0.9)
    else:  # simple deterministic circle fallback
        import math
        ordered = nodes["node"].tolist()
        pos = {node: (math.cos(2 * math.pi * i / len(ordered)), math.sin(2 * math.pi * i / len(ordered))) for i, node in enumerate(ordered)}

    edge_x, edge_y, edge_text = [], [], []
    for _, row in edges.iterrows():
        x0, y0 = pos[row["source"]]
        x1, y1 = pos[row["target"]]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]
        edge_text.append(f"{row['source']} — {row['target']}: {row['shared_works']} shared works")

    edge_trace = go.Scatter(
        x=edge_x,
        y=edge_y,
        mode="lines",
        line=dict(width=0.7, color="rgba(90,90,90,0.35)"),
        hoverinfo="skip",
        showlegend=False,
    )

    fig = go.Figure()
    fig.add_trace(edge_trace)
    for kind, group in nodes.groupby("kind"):
        xs = [pos[node][0] for node in group["node"]]
        ys = [pos[node][1] for node in group["node"]]
        sizes = [10 + min(float(v or 0), 30) for v in group["total_shared_works"]]
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="markers+text",
                text=group["node"],
                textposition="top center",
                marker=dict(size=sizes, line=dict(width=1, color="white")),
                name=kind,
                hovertemplate="%{text}<br>Type: " + kind + "<br>Total shared works: %{marker.size}<extra></extra>",
            )
        )
    fig.update_layout(
        title="Roster staff connected to external co-authors",
        xaxis=dict(showgrid=False, zeroline=False, visible=False),
        yaxis=dict(showgrid=False, zeroline=False, visible=False),
        margin=dict(l=10, r=10, t=50, b=10),
        height=650,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Edges represent shared works in the currently filtered publication set; node size increases with repeated collaboration.")


def render_collaborators_tab(bundle: Dict[str, Any], filtered: Dict[str, Any]) -> None:
    authorships = filtered["authorships"]

    st.subheader("Collaborator countries")
    external = authorships.copy()
    if "is_roster_person" in external.columns:
        external = external[external["is_roster_person"] == False]

    country_df = explode_json_list_column(external, "country_codes_json", "country_code")
    if country_df.empty:
        st.info("No external collaborator country data for the current filters.")
    else:
        country_summary = (
            country_df.groupby("country_code", as_index=False)
            .agg(
                external_authorship_rows=("work_id", "size"),
                collaborator_works=("work_id", "nunique"),
                unique_external_authors=("author_id_short", "nunique"),
            )
            .sort_values("collaborator_works", ascending=False)
        )
        country_summary["iso_alpha"] = country_summary["country_code"].apply(alpha2_to_alpha3)
        map_df = country_summary[country_summary["iso_alpha"].notna()].copy()

        left, right = st.columns([1.6, 1])
        with left:
            if map_df.empty:
                st.info("No mappable country codes after conversion.")
            else:
                fig = px.choropleth(
                    map_df,
                    locations="iso_alpha",
                    color="collaborator_works",
                    hover_name="country_code",
                    color_continuous_scale="Blues",
                    title="Collaborator works by country",
                )
                st.plotly_chart(fig, use_container_width=True)
        with right:
            st.dataframe(country_summary.head(25), use_container_width=True, hide_index=True)

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
        st.dataframe(top_insts, use_container_width=True, hide_index=True)

    _render_network(authorships)
