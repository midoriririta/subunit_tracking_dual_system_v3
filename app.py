from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from src.openalex_dashboard.cache_builder import build_cache_from_staff_csv, find_default_staff_csv
from src.openalex_dashboard.config import (
    BASE_PAGE_TITLE,
    CACHE_DIR,
    DATASET_CONFIGS,
    DEFAULT_DATASET_KEY,
    DEFAULT_OPENALEX_MAILTO,
    OUTPUT_DIR,
    RAW_DIR,
)
from src.openalex_dashboard.data import cache_status, clear_streamlit_cache, load_bundle
from src.openalex_dashboard.filters import apply_global_filters, render_sidebar_filters
from src.openalex_dashboard.views.collaborators import render_collaborators_tab
from src.openalex_dashboard.views.data_quality import render_data_quality_tab
from src.openalex_dashboard.views.domains_sources import render_domains_sources_tab
from src.openalex_dashboard.views.explorer import render_explorer_tab
from src.openalex_dashboard.views.overview import render_overview_tab

st.set_page_config(page_title=BASE_PAGE_TITLE, page_icon="", layout="wide")


def sync_browser_title(title: str) -> None:
    safe_title = title.replace("'", "\\'")
    components.html(
        f"""
        <script>
        const newTitle = '{safe_title}';
        if (window.parent && window.parent.document) {{
            window.parent.document.title = newTitle;
        }} else {{
            document.title = newTitle;
        }}
        </script>
        """,
        height=0,
        width=0,
    )


def read_selected_dataset() -> str:
    params = st.query_params
    dataset_key = params.get("dataset", DEFAULT_DATASET_KEY)
    if isinstance(dataset_key, list):
        dataset_key = dataset_key[0]
    dataset_key = str(dataset_key).lower()
    if dataset_key not in DATASET_CONFIGS:
        dataset_key = DEFAULT_DATASET_KEY
    return dataset_key


def append_progress(message: str) -> None:
    st.session_state.setdefault("build_log", []).append(message)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except Exception:
        return str(path)


def render_cache_update_panel(dataset_key: str) -> None:
    """Render the upload/update controls at the end of the sidebar.

    The app uses existing bundled cache files by default. Nothing is re-scraped
    unless the user explicitly uploads a CSV and clicks the refresh button.
    """
    cfg = DATASET_CONFIGS[dataset_key]
    status = cache_status(dataset_key)
    default_staff_csv = find_default_staff_csv(dataset_key)

    with st.sidebar:
        st.divider()
        with st.expander("Upload new staff CSV to update cache", expanded=False):
            if status["complete"]:
                st.success("Using existing cache by default.")
            else:
                st.warning("Cache missing: " + ", ".join(status["missing"]))

            if default_staff_csv:
                st.caption(f"Bundled staff CSV: `{_display_path(default_staff_csv)}`")
            else:
                st.caption(f"No bundled staff CSV found for {cfg['label']}.")

            uploaded = st.file_uploader(
                "Upload replacement staff CSV",
                type=["csv"],
                help="This should be a staff/person CSV. The app will rebuild the OpenAlex publication cache only after you click the button below.",
            )
            mailto = st.text_input(
                "OpenAlex mailto",
                value=DEFAULT_OPENALEX_MAILTO or os.environ.get("OPENALEX_MAILTO", ""),
                help="Optional but recommended for OpenAlex polite-pool requests.",
            )
            max_candidates = st.number_input(
                "Max OpenAlex author candidates per staff member",
                min_value=1,
                max_value=5,
                value=2,
                step=1,
            )
            min_author_score = st.slider(
                "Minimum author-match score to fetch works",
                min_value=0.0,
                max_value=1.0,
                value=0.55,
                step=0.05,
            )
            refresh_clicked = st.button("Update cache from uploaded CSV", use_container_width=True)

    if refresh_clicked:
        if uploaded is None:
            st.error("Please upload a new staff CSV before updating the cache.")
            st.stop()
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        uploaded_path = RAW_DIR / f"{dataset_key}_uploaded_staff.csv"
        uploaded_path.write_bytes(uploaded.getvalue())
        st.session_state["build_log"] = []
        with st.spinner("Rebuilding OpenAlex cache from the uploaded staff CSV..."):
            try:
                result = build_cache_from_staff_csv(
                    input_csv=uploaded_path,
                    dataset_key=dataset_key,
                    cache_dir=CACHE_DIR,
                    output_dir=OUTPUT_DIR,
                    mailto=mailto,
                    max_candidates_per_person=int(max_candidates),
                    min_author_score=float(min_author_score),
                    progress=append_progress,
                )
            except Exception as exc:
                st.error(f"OpenAlex cache update failed: {exc}")
                if st.session_state.get("build_log"):
                    with st.expander("Build log", expanded=True):
                        st.code("\n".join(st.session_state["build_log"][-80:]))
                st.stop()
        clear_streamlit_cache()
        st.success("Updated the publication CSV and parquet cache from the uploaded staff CSV.")
        paths = result.get("paths", {})
        if paths.get("scraped_publications_csv"):
            st.info(f"Publication CSV written to `{paths['scraped_publications_csv']}`")
        st.rerun()


current_dataset_key = read_selected_dataset()
current_cfg = DATASET_CONFIGS[current_dataset_key]

switch_col, _ = st.columns([1.1, 4], gap="small")
with switch_col:
    selected_label = st.radio(
        "Department",
        options=[cfg["label"] for cfg in DATASET_CONFIGS.values()],
        index=list(DATASET_CONFIGS.keys()).index(current_dataset_key),
        horizontal=False,
    )

selected_dataset_key = next(key for key, cfg in DATASET_CONFIGS.items() if cfg["label"] == selected_label)
if selected_dataset_key != current_dataset_key:
    st.query_params["dataset"] = selected_dataset_key
    st.rerun()

selected_cfg = DATASET_CONFIGS[selected_dataset_key]
sync_browser_title(selected_cfg["title"])
st.title(f" {selected_cfg['title']}")
st.caption(selected_cfg["caption"])

try:
    bundle = load_bundle(selected_dataset_key)
except FileNotFoundError as exc:
    st.error(str(exc))
    st.info(
        "The app now uses existing cache files by default. Upload a staff CSV at the end of the sidebar to rebuild the cache."
    )
    render_cache_update_panel(selected_dataset_key)
    st.stop()

filters = render_sidebar_filters(bundle)
render_cache_update_panel(selected_dataset_key)
filtered = apply_global_filters(bundle, filters)

(
    tab_overview,
    tab_domains,
    tab_collab,
    tab_explorer,
    tab_quality,
) = st.tabs([
    "Overview",
    "Domains & Sources",
    "Collaborators",
    "Publications Explorer",
    "Data Quality",
])

with tab_overview:
    render_overview_tab(bundle, filtered)
with tab_domains:
    render_domains_sources_tab(bundle, filtered)
with tab_collab:
    render_collaborators_tab(bundle, filtered)
with tab_explorer:
    render_explorer_tab(bundle, filtered)
with tab_quality:
    render_data_quality_tab(bundle, filtered)
