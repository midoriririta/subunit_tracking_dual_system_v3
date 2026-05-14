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


# -----------------------------------------------------------------------------
# Small formatting / country-code helpers
# -----------------------------------------------------------------------------


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


def _clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).strip().split())


def _safe_bool_series(series: pd.Series) -> pd.Series:
    """Convert a possibly mixed boolean/string column to real booleans."""
    if series.empty:
        return pd.Series(dtype=bool)

    def as_bool(value: Any) -> bool:
        if value is None or pd.isna(value):
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        return text in {"true", "1", "yes", "y", "t"}

    return series.map(as_bool).fillna(False).astype(bool)


# -----------------------------------------------------------------------------
# Country and institution summaries
# -----------------------------------------------------------------------------


def _external_authorships(authorships: pd.DataFrame) -> pd.DataFrame:
    if authorships.empty:
        return authorships.copy()

    external = authorships.copy()
    if "is_roster_person" in external.columns:
        is_roster = _safe_bool_series(external["is_roster_person"])
        external = external[~is_roster].copy()
    return external


def _country_summary(external: pd.DataFrame) -> pd.DataFrame:
    country_df = explode_json_list_column(external, "country_codes_json", "country_code")
    if country_df.empty:
        return pd.DataFrame()

    required_cols = {"country_code", "work_id"}
    if not required_cols.issubset(country_df.columns):
        return pd.DataFrame()

    if "author_id_short" not in country_df.columns:
        country_df["author_id_short"] = None

    country_summary = (
        country_df.groupby("country_code", as_index=False)
        .agg(
            external_authorship_rows=("work_id", "size"),
            collaborator_works=("work_id", "nunique"),
            unique_external_authors=("author_id_short", "nunique"),
        )
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


# -----------------------------------------------------------------------------
# Collaboration network
# -----------------------------------------------------------------------------


def _make_author_nodes(authorships: pd.DataFrame) -> pd.DataFrame:
    """Create one unique author node per work/authorship row.

    Important: the previous version split rows into roster and external authors
    and only created roster -> external edges. That made direct internal
    co-authorships impossible to show. This node table keeps both groups and
    lets the edge builder add roster -> roster edges as well.
    """
    if authorships.empty or "work_id" not in authorships.columns:
        return pd.DataFrame()

    authors = authorships.copy()
    if "is_roster_person" not in authors.columns:
        authors["is_roster_person"] = False
    if "author_id_short" not in authors.columns:
        authors["author_id_short"] = None
    if "author_id_full" not in authors.columns:
        authors["author_id_full"] = None
    if "author_name" not in authors.columns:
        authors["author_name"] = None
    if "raw_author_name" not in authors.columns:
        authors["raw_author_name"] = None
    if "roster_person_name" not in authors.columns:
        authors["roster_person_name"] = None

    authors["is_roster_person"] = _safe_bool_series(authors["is_roster_person"])

    def display_name(row: pd.Series) -> str:
        if bool(row["is_roster_person"]):
            for col in ["roster_person_name", "author_name", "raw_author_name", "author_id_short", "author_id_full"]:
                value = _clean_text(row.get(col))
                if value:
                    return value
        else:
            for col in ["author_name", "raw_author_name", "author_id_short", "author_id_full"]:
                value = _clean_text(row.get(col))
                if value:
                    return value
        return "Unknown author"

    authors["display_name"] = authors.apply(display_name, axis=1)

    def node_id(row: pd.Series) -> str:
        if bool(row["is_roster_person"]):
            # Use the roster name as the stable staff node where possible, so the
            # same staff member stays a single node across papers even if OpenAlex
            # uses more than one author profile.
            key = _clean_text(row.get("roster_person_name")) or _clean_text(row.get("author_id_short")) or row["display_name"]
            return f"staff::{key.lower()}"

        # For external authors, prefer OpenAlex author IDs to avoid merging two
        # different collaborators who share a common name.
        key = _clean_text(row.get("author_id_short")) or _clean_text(row.get("author_id_full")) or row["display_name"]
        return f"external::{key.lower()}"

    authors["node_id"] = authors.apply(node_id, axis=1)
    authors["kind"] = authors["is_roster_person"].map({True: "Roster", False: "External collaborator"})

    keep_cols = ["work_id", "node_id", "display_name", "kind", "is_roster_person"]
    node_rows = authors[keep_cols].copy()
    node_rows = node_rows[(node_rows["work_id"].notna()) & (node_rows["node_id"].notna())]
    node_rows = node_rows.drop_duplicates(["work_id", "node_id"])
    return node_rows


def _build_collaboration_edges(
    authorships: pd.DataFrame,
    max_external_nodes: int = 35,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build a co-authorship graph for the selected publication set.

    Edges mean "these two authors appear on the same work". The graph includes:
    1. roster -> roster edges, to show direct internal collaboration;
    2. roster -> external edges, to show external collaborators.

    External -> external edges are intentionally omitted because they make the
    plot dense without adding much information about the unit/department's own
    collaboration pattern.
    """
    node_rows = _make_author_nodes(authorships)
    if node_rows.empty:
        return pd.DataFrame(), pd.DataFrame()

    edge_rows: list[dict[str, Any]] = []
    for work_id, work_nodes in node_rows.groupby("work_id"):
        work_nodes = work_nodes.drop_duplicates("node_id")
        roster_nodes = work_nodes[work_nodes["kind"] == "Roster"]
        external_nodes = work_nodes[work_nodes["kind"] != "Roster"]

        if roster_nodes.empty:
            continue

        # Direct internal co-authorship: Charlie--Melinda and similar pairs.
        for left, right in combinations(roster_nodes["node_id"].tolist(), 2):
            source, target = sorted([left, right])
            edge_rows.append(
                {
                    "source": source,
                    "target": target,
                    "work_id": work_id,
                    "edge_kind": "Internal co-authorship",
                }
            )

        # Staff connected to external co-authors on the same paper.
        for source in roster_nodes["node_id"].tolist():
            for target in external_nodes["node_id"].tolist():
                if source != target:
                    edge_rows.append(
                        {
                            "source": source,
                            "target": target,
                            "work_id": work_id,
                            "edge_kind": "External collaboration",
                        }
                    )

    if not edge_rows:
        return pd.DataFrame(), pd.DataFrame()

    pairs = pd.DataFrame(edge_rows)
    edges = (
        pairs.groupby(["source", "target", "edge_kind"], as_index=False)
        .agg(shared_works=("work_id", "nunique"))
        .sort_values(["edge_kind", "shared_works"], ascending=[True, False])
    )

    # Keep all internal staff-staff edges. Limit only external nodes to avoid a
    # very dense hairball when the publication set is large.
    external_edges = edges[edges["edge_kind"] == "External collaboration"].copy()
    if not external_edges.empty:
        external_strength = (
            external_edges.groupby("target", as_index=False)["shared_works"]
            .sum()
            .nlargest(max_external_nodes, "shared_works")
        )
        keep_external_nodes = set(external_strength["target"])
        edges = edges[
            (edges["edge_kind"] == "Internal co-authorship")
            | (edges["target"].isin(keep_external_nodes))
        ].copy()

    if edges.empty:
        return pd.DataFrame(), pd.DataFrame()

    node_meta = (
        node_rows[["node_id", "display_name", "kind"]]
        .drop_duplicates("node_id")
        .rename(columns={"node_id": "node"})
    )
    nodes_in_edges = sorted(set(edges["source"]).union(edges["target"]))
    nodes = pd.DataFrame({"node": nodes_in_edges}).merge(node_meta, on="node", how="left")
    nodes["display_name"] = nodes["display_name"].fillna(nodes["node"])
    nodes["kind"] = nodes["kind"].fillna("External collaborator")

    degree_weight = pd.concat(
        [
            edges[["source", "shared_works"]].rename(columns={"source": "node"}),
            edges[["target", "shared_works"]].rename(columns={"target": "node"}),
        ],
        ignore_index=True,
    )
    nodes = nodes.merge(
        degree_weight.groupby("node", as_index=False).agg(total_shared_works=("shared_works", "sum")),
        on="node",
        how="left",
    )
    nodes["total_shared_works"] = nodes["total_shared_works"].fillna(0)

    # Extra hover metrics, useful for checking direct staff links.
    staff_edges = edges[edges["edge_kind"] == "Internal co-authorship"]
    staff_link_rows = []
    for _, row in staff_edges.iterrows():
        staff_link_rows.append({"node": row["source"], "other": row["target"]})
        staff_link_rows.append({"node": row["target"], "other": row["source"]})
    if staff_link_rows:
        staff_link_counts = (
            pd.DataFrame(staff_link_rows).groupby("node", as_index=False).agg(direct_staff_collaborators=("other", "nunique"))
        )
        nodes = nodes.merge(staff_link_counts, on="node", how="left")
    else:
        nodes["direct_staff_collaborators"] = 0

    external_link_rows = []
    for _, row in external_edges.iterrows():
        if row["target"] in set(nodes["node"]):
            external_link_rows.append({"node": row["source"], "other": row["target"]})
            external_link_rows.append({"node": row["target"], "other": row["source"]})
    if external_link_rows:
        external_link_counts = (
            pd.DataFrame(external_link_rows).groupby("node", as_index=False).agg(external_collaborator_links=("other", "nunique"))
        )
        nodes = nodes.merge(external_link_counts, on="node", how="left")
    else:
        nodes["external_collaborator_links"] = 0

    nodes["direct_staff_collaborators"] = nodes["direct_staff_collaborators"].fillna(0).astype(int)
    nodes["external_collaborator_links"] = nodes["external_collaborator_links"].fillna(0).astype(int)
    return nodes, edges


def _fallback_positions(nodes: pd.DataFrame) -> dict[str, tuple[float, float]]:
    import math

    roster_nodes = nodes[nodes["kind"] == "Roster"]["node"].tolist()
    external_nodes = nodes[nodes["kind"] != "Roster"]["node"].tolist()
    pos: dict[str, tuple[float, float]] = {}

    # Put staff in the centre and external collaborators around them.
    for i, node in enumerate(roster_nodes):
        angle = 2 * math.pi * i / max(len(roster_nodes), 1)
        pos[node] = (0.45 * math.cos(angle), 0.45 * math.sin(angle))
    for i, node in enumerate(external_nodes):
        angle = 2 * math.pi * i / max(len(external_nodes), 1)
        pos[node] = (1.25 * math.cos(angle), 1.25 * math.sin(angle))
    return pos


def _layout_network(nodes: pd.DataFrame, edges: pd.DataFrame) -> dict[str, tuple[float, float]]:
    if nx is None:
        return _fallback_positions(nodes)

    graph = nx.Graph()
    for _, row in nodes.iterrows():
        graph.add_node(row["node"], kind=row["kind"], weight=float(row["total_shared_works"] or 0))
    for _, row in edges.iterrows():
        graph.add_edge(row["source"], row["target"], weight=float(row["shared_works"] or 1))

    if graph.number_of_nodes() == 0:
        return {}
    if graph.number_of_nodes() == 1:
        only = next(iter(graph.nodes()))
        return {only: (0.0, 0.0)}

    try:
        return nx.spring_layout(
            graph,
            seed=7,
            k=max(0.45, 2.2 / (graph.number_of_nodes() ** 0.5)),
            iterations=120,
            weight="weight",
        )
    except Exception:
        return _fallback_positions(nodes)


def _edge_trace(
    edges: pd.DataFrame,
    pos: dict[str, tuple[float, float]],
    edge_kind: str,
    line_color: str,
    line_width: float,
) -> go.Scatter:
    selected = edges[edges["edge_kind"] == edge_kind]
    edge_x: list[float | None] = []
    edge_y: list[float | None] = []

    for _, row in selected.iterrows():
        if row["source"] not in pos or row["target"] not in pos:
            continue
        x0, y0 = pos[row["source"]]
        x1, y1 = pos[row["target"]]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    return go.Scatter(
        x=edge_x,
        y=edge_y,
        mode="lines",
        line=dict(width=line_width, color=line_color),
        hoverinfo="skip",
        name=edge_kind,
        showlegend=True,
    )


def _edge_hover_trace(edges: pd.DataFrame, nodes: pd.DataFrame, pos: dict[str, tuple[float, float]]) -> go.Scatter:
    name_lookup = nodes.set_index("node")["display_name"].to_dict()
    mid_x: list[float] = []
    mid_y: list[float] = []
    hover_text: list[str] = []

    for _, row in edges.iterrows():
        source = row["source"]
        target = row["target"]
        if source not in pos or target not in pos:
            continue
        x0, y0 = pos[source]
        x1, y1 = pos[target]
        mid_x.append((x0 + x1) / 2)
        mid_y.append((y0 + y1) / 2)
        hover_text.append(
            f"<b>{name_lookup.get(source, source)}</b> — <b>{name_lookup.get(target, target)}</b><br>"
            f"Type: {row['edge_kind']}<br>"
            f"Shared works: {int(row['shared_works']):,}"
        )

    return go.Scatter(
        x=mid_x,
        y=mid_y,
        mode="markers",
        marker=dict(size=14, color="rgba(0,0,0,0)", line=dict(width=0, color="rgba(0,0,0,0)")),
        text=hover_text,
        hovertemplate="%{text}<extra></extra>",
        showlegend=False,
        name="Edge details",
    )


def _render_network(authorships: pd.DataFrame) -> None:
    st.subheader("Collaboration network")
    nodes, edges = _build_collaboration_edges(authorships)
    if nodes.empty or edges.empty:
        st.info("No co-author network can be drawn for the current filters.")
        return

    internal_edges = edges[edges["edge_kind"] == "Internal co-authorship"]
    external_edges = edges[edges["edge_kind"] == "External collaboration"]

    m1, m2, m3 = st.columns(3)
    m1.metric("Staff nodes", format_int((nodes["kind"] == "Roster").sum()))
    m2.metric("Direct staff-staff links", format_int(len(internal_edges)))
    m3.metric("Shown external collaborators", format_int((nodes["kind"] != "Roster").sum()))

    if internal_edges.empty:
        st.warning(
            "No direct staff-staff co-authorship edge is present under the current filters. "
            "This means the filtered OpenAlex authorship table does not contain a shared work between two roster staff members."
        )

    pos = _layout_network(nodes, edges)
    if not pos:
        st.info("The collaboration network could not be laid out for the current filters.")
        return

    # Show labels for all roster staff and the strongest external collaborators.
    label_nodes = set(nodes[nodes["kind"] == "Roster"]["node"])
    top_external_labels = set(
        nodes[nodes["kind"] != "Roster"].nlargest(12, "total_shared_works")["node"].tolist()
    )
    label_nodes |= top_external_labels

    fig = go.Figure()

    if not external_edges.empty:
        fig.add_trace(
            _edge_trace(
                edges,
                pos,
                edge_kind="External collaboration",
                line_color="rgba(86,105,128,0.24)",
                line_width=0.8,
            )
        )
    if not internal_edges.empty:
        fig.add_trace(
            _edge_trace(
                edges,
                pos,
                edge_kind="Internal co-authorship",
                line_color="rgba(20,88,160,0.72)",
                line_width=2.2,
            )
        )

    fig.add_trace(_edge_hover_trace(edges, nodes, pos))

    for kind, group in nodes.groupby("kind", sort=False):
        group = group.copy()
        xs = [pos[node][0] for node in group["node"]]
        ys = [pos[node][1] for node in group["node"]]
        shared = group["total_shared_works"].fillna(0).astype(float)
        sizes = 12 + (shared ** 0.5 * 6).clip(upper=32)
        group["label"] = group.apply(
            lambda row: row["display_name"] if row["node"] in label_nodes else "",
            axis=1,
        )
        customdata = group[
            [
                "display_name",
                "kind",
                "total_shared_works",
                "direct_staff_collaborators",
                "external_collaborator_links",
            ]
        ].to_numpy()

        if kind == "Roster":
            marker = dict(
                size=sizes,
                color="rgba(31,119,180,0.92)",
                line=dict(width=1.5, color="white"),
                opacity=0.95,
            )
        else:
            marker = dict(
                size=sizes,
                color="rgba(120,144,156,0.72)",
                line=dict(width=1.0, color="white"),
                opacity=0.82,
            )

        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="markers+text",
                text=group["label"],
                textposition="top center",
                customdata=customdata,
                marker=marker,
                name=kind,
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Type: %{customdata[1]}<br>"
                    "Total shared works: %{customdata[2]:,}<br>"
                    "Direct staff collaborators: %{customdata[3]:,}<br>"
                    "Shown external collaborator links: %{customdata[4]:,}"
                    "<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        title=(
            "Co-authorship network: direct staff-staff collaborations plus strongest external collaborators"
        ),
        xaxis=dict(showgrid=False, zeroline=False, visible=False),
        yaxis=dict(showgrid=False, zeroline=False, visible=False),
        margin=dict(l=10, r=10, t=55, b=10),
        height=680,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "A direct staff-staff edge is drawn when two roster staff appear on the same OpenAlex work. "
        "External-external edges are omitted to keep the graph focused; only the strongest external collaborators are shown."
    )

    with st.expander("Inspect strongest direct staff-staff collaborations", expanded=False):
        if internal_edges.empty:
            st.info("No direct staff-staff edges under the current filters.")
        else:
            name_lookup = nodes.set_index("node")["display_name"].to_dict()
            internal_table = internal_edges.copy()
            internal_table["staff_1"] = internal_table["source"].map(name_lookup)
            internal_table["staff_2"] = internal_table["target"].map(name_lookup)
            internal_table = internal_table[["staff_1", "staff_2", "shared_works"]].sort_values(
                "shared_works", ascending=False
            )
            st.dataframe(
                internal_table.head(50),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "staff_1": "Staff member 1",
                    "staff_2": "Staff member 2",
                    "shared_works": "Shared works",
                },
            )


# -----------------------------------------------------------------------------
# Public tab renderer
# -----------------------------------------------------------------------------


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
        if "author_id_short" not in inst_df.columns:
            inst_df["author_id_short"] = None

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
